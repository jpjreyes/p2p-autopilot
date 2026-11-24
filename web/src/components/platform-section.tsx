import Image from "next/image";
import { ArrowRight } from "lucide-react";
import { Card, Stat } from "@/components/ui";

const REPO = "https://github.com/jpjreyes/p2p-autopilot";
const DECISIONS_URL = `${REPO}/blob/main/DECISIONS.md`;

// Static results (DECISIONS D28-D33). Nothing here calls the API: the numbers come from the scored runs in the repo.
const READER: [string, string, string, string, string?][] = [
  ["Qwen3-VL-4B, untuned", "85.0%", "78%", "77%"],
  ["Qwen3-VL-4B, fine-tuned (QLoRA)", "91.9%", "84%", "63%", "ours"],
  ["Claude Haiku (reference)", "97.1%", "96%", "100%"],
];

const STEPS: [string, string][] = [
  ["Arrive", "the day's SAP extract file lands"],
  ["Ingest", "Auto Loader picks up only new files, exactly once"],
  ["Build", "dbt models + 24 data tests"],
  ["Score", "champion model from the MLflow registry"],
  ["Drift", "PSI vs the calibration month"],
  ["Brief", "weekly numbers, on Sundays"],
];

const ENGINES: [string, string, string][] = [
  ["DuckDB", "local and in CI", "identical to the original Python build, row for row (1.6M events)"],
  ["Databricks", "live daily job (Free Edition)", "identical to DuckDB on the same files; scores exactly equal"],
  ["Snowflake", "tested target (trial)", "33/33 models and tests on the first build; identical tables"],
  ["Airflow", "the same steps as a DAG, run locally", "daily worklists identical to the Databricks job"],
];

const SHOTS: [string, string, number][] = [
  ["/platform/databricks-job-runs.jpg", "Databricks daily job: run history, every task green", 737],
  ["/platform/databricks-task-graph.jpg", "One run: arrive, ingest, dbt build, score", 737],
  ["/platform/databricks-lineage.jpg", "Unity Catalog lineage, built from the dbt models", 737],
  ["/platform/airflow-dag-runs.jpg", "The same steps as an Airflow DAG", 782],
];

export function PlatformSection() {
  return (
    <section className="space-y-8 border-t border-line-strong pt-10">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">Models and data platform</h2>
        <p className="mt-1 max-w-3xl text-sm text-muted">
          Beyond the agent: a reader model that runs on the company&apos;s own hardware, one registry for both models,
          and the pipeline that feeds the warehouse every day. Every number below was scored once on held-out data;
          the reasoning is in <a href={DECISIONS_URL} className="text-brand underline underline-offset-2">DECISIONS.md</a> (D28 to D33).
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <Stat label="Receipts read, own 4B model" value="92%" note="untuned 85% · Claude 97% · 347 real receipts" />
        <Stat label="Same tables on 3 engines" value="3/3" tone="ok" note="DuckDB, Databricks, Snowflake, row for row" />
        <Stat label="Daily top 10, real replay" value="92.4%" note="test months fed day by day (claimed 92.0%)" />
        <Stat label="Databricks job vs Airflow" value="100%" tone="ok" note="identical worklists on every replay day" />
      </div>

      <div>
        <h3 className="font-semibold tracking-tight">Reading documents with a fine-tuned open model</h3>
        <p className="mb-4 mt-1 text-sm text-muted">
          Total and date both right. Fine-tuned on 445 real receipts on one free GPU, so documents never leave the
          company. The point is privacy, not cost.
        </p>
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-line bg-surface-2 text-left text-xs uppercase tracking-wide text-faint">
                <tr>
                  <th className="px-5 py-3 font-medium">Model</th>
                  <th className="px-5 py-3 font-medium">Real receipts (347)</th>
                  <th className="px-5 py-3 font-medium">Companies never seen (100)</th>
                  <th className="px-5 py-3 font-medium">Invoices (92)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {READER.map(([name, all, unseen, inv, ours]) => (
                  <tr key={name} className={ours ? "bg-surface-2" : ""}>
                    <td className="px-5 py-3 font-medium">{name}</td>
                    <td className="tabular px-5 py-3">{all}</td>
                    <td className="tabular px-5 py-3">{unseen}</td>
                    <td className="tabular px-5 py-3">{inv}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <p className="mt-3 max-w-3xl text-sm text-muted">
          Trained only on receipts, it got worse on invoices: it reads the due date as the date. The code check against
          the portal row still catches every miss: small model first, Claude on 37% of invoices, <b className="text-foreground">100%
          right, 0 silent errors</b>.
        </p>
      </div>

      <div>
        <h3 className="font-semibold tracking-tight">The daily pipeline</h3>
        <p className="mb-4 mt-1 text-sm text-muted">
          The SAP data lives in the customer&apos;s warehouse, so the build is tested dbt SQL that gives the same tables on
          whichever engine they run. The test months are replayed one day at a time and only scored, never trained on.
        </p>
        <ol className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          {STEPS.map(([name, what], i) => (
            <li key={name} className="relative rounded-lg border border-line p-3">
              <span className="label text-faint">{i + 1}</span>
              <b className="block text-sm">{name}</b>
              <span className="block text-xs text-muted">{what}</span>
              {i < STEPS.length - 1 && (
                <ArrowRight className="absolute -right-2.5 top-1/2 hidden size-4 -translate-y-1/2 text-faint lg:block" />
              )}
            </li>
          ))}
        </ol>
        <Card className="mt-4 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-line bg-surface-2 text-left text-xs uppercase tracking-wide text-faint">
                <tr>
                  <th className="px-5 py-3 font-medium">Runs on</th>
                  <th className="px-5 py-3 font-medium">Role</th>
                  <th className="px-5 py-3 font-medium">Parity check</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {ENGINES.map(([name, role, parity]) => (
                  <tr key={name}>
                    <td className="px-5 py-3 font-medium">{name}</td>
                    <td className="px-5 py-3 text-muted">{role}</td>
                    <td className="px-5 py-3">{parity}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <ul className="grid gap-3 text-sm text-muted md:grid-cols-3">
        <li className="rounded-lg border border-line p-4">
          <b className="text-foreground">Promotion by a rule written first.</b> Both models live in an MLflow registry. A
          payment-block challenger was rejected by the gate; the reader passed it (held-out 50: 86% to 100%).
        </li>
        <li className="rounded-lg border border-line p-4">
          <b className="text-foreground">Drift is watched, not obeyed.</b> Inputs drift while the score holds (PSI 0.05):
          a reason to check performance when labels arrive, never to stop or retrain.
        </li>
        <li className="rounded-lg border border-line p-4">
          <b className="text-foreground">A leak check runs in CI.</b> It found one feature counting order lines created
          after the invoice. It did not inflate the 92%: the replay can&apos;t see later lines and scores 92.4%.
        </li>
      </ul>

      <div className="grid gap-4 sm:grid-cols-2">
        {SHOTS.map(([src, caption, h]) => (
          <figure key={src}>
            <a href={src} target="_blank" rel="noreferrer">
              <Image src={src} alt={caption} width={1568} height={h} className="w-full rounded-lg border border-line" />
            </a>
            <figcaption className="mt-1.5 text-xs text-muted">{caption}</figcaption>
          </figure>
        ))}
      </div>

      <p className="text-sm text-muted">
        Code and every number:{" "}
        <a href={`${REPO}#models-and-mlops`} className="text-brand underline underline-offset-2" target="_blank" rel="noreferrer">
          README · Models and MLOps · Data platform
        </a>
      </p>
    </section>
  );
}
