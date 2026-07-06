# Log entry body — worked example

The `text` body of a `level=detail` log entry is a small Markdown document, not a flat sentence. SKILL.md → "Log Entry Body Schema" defines the required sections (`## title` + `Context` / `Operations` / `Result`/`Verification` / `Decisions`/`Open`). This file holds a full worked example.

## Good example

```text
## Spark Java 17 image build pushed to dev branch, registry push blocked

Context
- Triggered by user request 2026-05-13: produce a Java 17 Spark image consumable by Kyuubi prod and DolphinScheduler.
- Branch: spark-3.5.7-java17-image-c93fa99e, base commit c93fa99e8254. Continues the 2026-05-13 12:53 build log entry.

Operations
- Edited `/data/workspace/spark/pom.xml` and `/data/workspace/spark/assembly/pom.xml`: set `java.version=17`, removed legacy `--add-opens` entries.
- Ran `/data/workspace/spark/build-spark-image-local.sh` after `export SPARK_HOME=/data/workspace/spark/dist` to stop `docker-image-tool` from picking up `/opt/spark` from the host.
- Built images `hub.i.basemind.com/spark/spark:3.5.7-STEP-rc2-c93fa99e8254-java17` (b2015d776c99, 1.47GB) and `spark-py:<same tag>` (d211d518df6c, 1.54GB).
- Committed and pushed at 178c3a2b2d on origin/spark-3.5.7-java17-image-c93fa99e.

Verification
- Local smoke: Ubuntu 22.04 jammy, Java 17.0.18, Spark 3.5.7-STEP-rc2, PySpark import OK, SparkPi OK.
- Registry push: BLOCKED. `hub.i.basemind.com/spark/{spark,spark-py}` → 401 unauthorized; `registry.platform.shaipower.com/spark/*` → denied; `hub.i.basemind.com/wanganyang/*` project does not exist.
- Kyuubi prod baseline still alive: beeline `jdbc:hive2://10.130.33.104:10009/default`, `SELECT 1` → 1, app `spark-2c2f46fe193841378c26a7a6eb3772a5`.
- Prod validation of the new image: NOT RUN, image is not yet pushable.

Decisions / Open
- Need a writable registry path before prod can pull the new image. Ask user: which `hub.i.basemind.com` namespace has push rights for this account; or stand up a personal Harbor project.
- Until then, image lives only on the local host.
```

## Bad example — do not write entries that look like this

```text
Built local Java17 Spark image; smoke passed; not pushed yet.
```

This skips Context, hides which paths were touched, omits commit SHA, omits the failure mode (`not pushed yet` does not say why), and is unreproducible. A future session must re-investigate from scratch.
