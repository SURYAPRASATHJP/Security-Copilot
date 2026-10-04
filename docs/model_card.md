# Model card: prompt injection classifier

## What it is for

It decides whether a piece of text is trying to change the copilot's instructions rather
than ask it something. It runs on two kinds of input: questions a user types, and text that
arrives from somewhere else, which means advisory bodies from public databases and files
from a repository under scan. The second kind is the reason it exists. A user who tries an
injection is a nuisance; an advisory that carries one is a supply chain problem, because
nobody typed it and nobody read it.

It is one layer, not the defence. The agent is handed only read-only tools, writes need a
human approval, and the output guard checks citations and versions independently. A miss
here does not by itself cause a write.

## The three candidates

All three were trained or evaluated on the same split, so the numbers compare.

| Model | Precision | Recall | F1 | Threshold | ms per row | Where it runs |
| --- | --- | --- | --- | --- | --- | --- |
| Pattern rule | 1.000 | 0.086 | 0.159 | n/a | under 0.1 | locally, no model |
| TF-IDF and logistic regression | 0.779 | 0.914 | 0.841 | 0.45 | under 0.1 | locally, CPU |
| **DistilBERT, fine-tuned** | **0.963** | **0.975** | **0.969** | 0.5 | 26.5 | locally, CPU |

Cross-validated F1 for the baseline was 0.840 with a spread of 0.032 over 5 folds, so its
test score of 0.841 is where the folds said it would be rather than a lucky split.

Llama Prompt Guard 2 is supported by the same interface but is not in this table. Every
prediction is a billed API call against a 200,000 token daily ceiling, which makes it the
wrong tool for text that arrives on every retrieval. `compare_classifiers.py` will score it
on a sample when run without `--skip-prompt-guard`.

## What was chosen, and why

**DistilBERT.** Recall is the number that matters: a false alarm costs a developer one
rephrase, a miss lets an instruction through into a prompt. It is best on recall and best
on precision at the same time, so there is no trade to argue about.

The pattern rule stays in front of it. It costs nothing, it never raises a false alarm on
this data, and it answers in microseconds, so it catches the obvious attempts before
anything is loaded. The classifier is what catches the other 91 percent.

The baseline is not wasted. It is five orders of magnitude cheaper to retrain, which makes
it the right thing to re-run when the training data changes, and its learning curve is what
says whether the next model is limited by data or by capacity.

## Threshold

DistilBERT is used at its default 0.5. The baseline's threshold was tuned to 0.45, chosen
as the most recall available while precision stayed above 0.75. The rule for both: when in
doubt, flag it. The cost of being wrong is asymmetric and the asymmetry is not close.

## Training data

942 rows after exact duplicates were removed, split 708 train and 234 test.

| Source | Rows | Label |
| --- | --- | --- |
| `deepset/prompt-injections` | 662 | both |
| This project's red team set | 64 | injection |
| The generated golden questions | 216 | benign |

327 injections and 615 benign, so the smallest class is 34.7 percent of each split. Seven
checks run in `data_checks.py` before training: schema, no empty text, no unknown label or
source, no duplicates, label balance above 15 percent, and no text appearing in both halves.
All seven pass. The leakage check is the one that matters, because without it a test score
measures memory rather than learning.

## Known weaknesses

- **The red team rows are ours.** 64 of the 327 injections were written for this project,
  so the model has seen the shape of the attacks we thought of. That flatters it against
  our own red team set and says nothing about attacks nobody has written down.
- **English only.** The public dataset is overwhelmingly English and so are the questions.
  An injection in another language is untested.
- **Short text.** Inputs are truncated at 256 tokens. An attack buried deep in a long
  advisory is checked in windows by the input guard, but the classifier only sees each
  window, never the whole document at once.
- **It cannot see intent.** A legitimate question quoting an attack, such as a developer
  asking what an injection looks like, reads like an attack. That is a deliberate trade:
  the input guard blocks, the user rephrases.
- **The benign half is narrow.** The golden questions are generated from a template, so
  real developer phrasing is under-represented and the false alarm rate on real traffic is
  likely higher than 0.037 suggests.

## Reproducing it

```sh
uv run python -m copilot.ml.build_training_data
uv run python -m copilot.ml.data_checks
uv run python -m copilot.ml.train_baseline_classifier
uv run python -m copilot.ml.finetune_distilbert
uv run python -m copilot.ml.compare_classifiers
```

Every run is logged to MLflow under the `prompt-injection-classifier` experiment, and the
data and model are tracked by the DVC pipeline in `dvc.yaml`.
