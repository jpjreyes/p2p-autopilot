"""Kaggle GPU job (one T4): untuned baseline -> QLoRA fine-tune -> fine-tuned predictions (DECISIONS D28).

Runs top to bottom as a Kaggle script. Everything it produces goes to /kaggle/working:
    preds_{base,ft}_{val,test,inv}.jsonl   one JSON answer per receipt / generated invoice scan
    adapter/                                                  the LoRA adapter (not published, see D28)
    train_log.json, run_info.json                             loss curve, settings, timings, library versions
Scoring happens once on the laptop (evals/finetune/score.py); this job never reads test labels.
"""

import os
os.environ["CUDA_VISIBLE_DEVICES"] = "0"  # one T4; Unsloth trains on a single GPU

import subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "unsloth==2026.11.9", "unsloth_zoo"], check=True)

import glob, json, re, time
from pathlib import Path

SMOKE = False                # True: a few receipts and steps, to catch bugs before the real run
MODEL = "unsloth/Qwen3-VL-4B-Instruct"
LORA_R, LORA_ALPHA = 16, 16
EPOCHS, LR, GRAD_ACCUM = 2, 2e-4, 8
MAX_LEN = 4096               # long enough that image tokens are never cut
MAX_NEW_TOKENS = 256
SEED = 3407

INSTRUCTION = """You extract fields from scanned receipts and invoices for accounts payable.
Return exactly what the document says; never compute or guess values that are not printed.
- company: the seller's name exactly as printed (usually at the top).
- address: the seller's address as printed, on one line.
- date: the document date as ISO YYYY-MM-DD. Read the date format from the document's conventions
  (US MM/DD/YYYY, European/Asian DD/MM/YYYY, or ISO).
- total: the final amount the customer pays, as a plain decimal string with a dot and no thousands
  separators: "1234.50".
Answer with only a JSON object with the keys company, address, date, total."""

DATA = Path(glob.glob("/kaggle/input/**/train.jsonl", recursive=True)[0]).parent
OUT = Path("/kaggle/working")
info = {"model": MODEL, "lora_r": LORA_R, "lora_alpha": LORA_ALPHA, "epochs": EPOCHS, "lr": LR,
        "grad_accum": GRAD_ACCUM, "max_len": MAX_LEN, "seed": SEED, "smoke": SMOKE, "timings_s": {}}


def rows(name):
    return [json.loads(x) for x in (DATA / name).read_text().splitlines()]


train, val, test = rows("train.jsonl"), rows("val.jsonl"), rows("test.jsonl")
inv = [{**r, "file": "invoices/images/" + r["file"]} for r in rows("invoices/invoices.jsonl")]
if SMOKE:
    train, val, test, inv = train[:16], val[:3], test[:3], inv[:2]

from PIL import Image
import torch
from unsloth import FastVisionModel, is_bf16_supported

info["gpu"] = torch.cuda.get_device_name(0)
print("GPU:", info["gpu"], "| data:", DATA, "| train/val/test/invoices:", len(train), len(val), len(test), len(inv),
      flush=True)


def image(file):
    return Image.open(DATA / (file if file.startswith("invoices/") else "images/" + file)).convert("RGB")


def parse(text):
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None


def predict(model, tokenizer, items, path):
    FastVisionModel.for_inference(model)
    done = {json.loads(x)["file"] for x in open(path)} if path.exists() else set()
    todo = [r for r in items if r["file"] not in done]
    t0 = time.time()
    with open(path, "a") as f:
        for i, r in enumerate(todo, 1):
            msgs = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": INSTRUCTION}]}]
            prompt = tokenizer.apply_chat_template(msgs, add_generation_prompt=True)
            inputs = tokenizer(image(r["file"]), prompt, add_special_tokens=False, return_tensors="pt").to("cuda")
            s = time.time()
            with torch.no_grad():
                out = model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False, use_cache=True)
            raw = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
            f.write(json.dumps({"file": r["file"], "answer": parse(raw), "raw": raw,
                                "latency_s": round(time.time() - s, 2)}) + "\n")
            f.flush()
            if i % 10 == 0 or i == len(todo):
                eta = (time.time() - t0) / i * (len(todo) - i)
                print(f"{path.name}: {i}/{len(todo)}, ETA {eta / 60:.1f} min", flush=True)
    return time.time() - t0


model, tokenizer = FastVisionModel.from_pretrained(MODEL, load_in_4bit=True, use_gradient_checkpointing="unsloth")

# 1. untuned baseline (same 4-bit model, same prompt)
info["timings_s"]["base_val"] = predict(model, tokenizer, val, OUT / "preds_base_val.jsonl")
info["timings_s"]["base_test"] = predict(model, tokenizer, test, OUT / "preds_base_test.jsonl")
info["timings_s"]["base_inv"] = predict(model, tokenizer, inv, OUT / "preds_base_inv.jsonl")

# 2. QLoRA fine-tune
from trl import SFTTrainer, SFTConfig
from unsloth.trainer import UnslothVisionDataCollator

model = FastVisionModel.get_peft_model(
    model, finetune_vision_layers=True, finetune_language_layers=True, finetune_attention_modules=True,
    finetune_mlp_modules=True, r=LORA_R, lora_alpha=LORA_ALPHA, lora_dropout=0, bias="none", random_state=SEED)


def example(r):
    return {"messages": [
        {"role": "user", "content": [{"type": "image", "image": image(r["file"])}, {"type": "text", "text": INSTRUCTION}]},
        {"role": "assistant", "content": [{"type": "text", "text": json.dumps(r["target"], ensure_ascii=False)}]},
    ]}


FastVisionModel.for_training(model)
trainer = SFTTrainer(
    model=model, tokenizer=tokenizer, data_collator=UnslothVisionDataCollator(model, tokenizer),
    train_dataset=[example(r) for r in train],
    args=SFTConfig(
        per_device_train_batch_size=1, gradient_accumulation_steps=GRAD_ACCUM, warmup_steps=5,
        num_train_epochs=EPOCHS, max_steps=3 if SMOKE else -1, learning_rate=LR, logging_steps=1 if SMOKE else 5,
        optim="adamw_8bit", weight_decay=0.01, lr_scheduler_type="linear", seed=SEED, output_dir="outputs",
        report_to="none", remove_unused_columns=False, dataset_text_field="",
        dataset_kwargs={"skip_prepare_dataset": True}, max_length=MAX_LEN,
        fp16=not is_bf16_supported(), bf16=is_bf16_supported()),
)
t0 = time.time()
stats = trainer.train()
info["timings_s"]["train"] = time.time() - t0
info["train_steps"] = stats.global_step
info["peak_gpu_gb"] = round(torch.cuda.max_memory_reserved() / 1e9, 2)
(OUT / "train_log.json").write_text(json.dumps(trainer.state.log_history, indent=1))
model.save_pretrained(str(OUT / "adapter"))
tokenizer.save_pretrained(str(OUT / "adapter"))

# 3. fine-tuned predictions
info["timings_s"]["ft_val"] = predict(model, tokenizer, val, OUT / "preds_ft_val.jsonl")
info["timings_s"]["ft_test"] = predict(model, tokenizer, test, OUT / "preds_ft_test.jsonl")
info["timings_s"]["ft_inv"] = predict(model, tokenizer, inv, OUT / "preds_ft_inv.jsonl")

import importlib.metadata as md
info["versions"] = {p: md.version(p) for p in ("torch", "transformers", "trl", "peft", "unsloth", "unsloth_zoo", "bitsandbytes")}
(OUT / "run_info.json").write_text(json.dumps(info, indent=1))
print("DONE", json.dumps(info["timings_s"]), "peak GPU GB", info["peak_gpu_gb"], flush=True)
