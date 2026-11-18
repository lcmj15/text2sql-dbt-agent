.PHONY: install data dbt expected test ask eval all

install:
	pip install -r requirements.txt

data:            ## regenerate the synthetic seed CSVs (deterministic)
	python data/generate_data.py

dbt:             ## seed + run + test the dbt project, then build the docs artifacts
	mkdir -p warehouse
	cd dbt_project && dbt build --profiles-dir . && dbt docs generate --profiles-dir .

expected:        ## materialize the golden answers to eval/expected_answers.json
	python -m eval.build_expected

test:            ## offline tests (no API key needed)
	pytest -q

ask:             ## make ask Q="How many conversions did we have in Q3 2025?"
	python -m agent.cli "$(Q)"

eval:            ## full evaluation, both modes, 3 runs
	python -m eval.evaluate --runs 3

all: dbt expected test eval
