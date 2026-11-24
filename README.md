# Heritage Short

A 60–90 second family film, regenerated from one file: `storyboard.json`.

> Work in progress — this README is completed at the end of the build.

## Quick start

```bash
git clone https://github.com/gecher/heritage-short && cd heritage-short
python -m pip install -r requirements.txt
cp .env.example .env          # add your keys (never commit .env)
python -m pipeline smoke      # one call per provider, logged to runs.jsonl
python -m pipeline validate   # check the storyboard contract
python -m pipeline film       # build the whole film (make film does the same)
```
