PYTHON ?= python3
SOLVER_DIR := third_party/RecursivePartitioningAlgorithm

.PHONY: all solver test validate check clean

all: solver

solver:
	$(MAKE) -C $(SOLVER_DIR)

test: solver
	$(PYTHON) -m unittest discover -s tests -v

validate: solver
	$(PYTHON) validation/end_to_end.py validation/data/learn_raw.jsonl validation/data/holdout_raw.jsonl
	$(PYTHON) validation/summary_check.py
	$(PYTHON) validation/targeted_check.py

check: test validate

clean:
	rm -f $(SOLVER_DIR)/*.o $(SOLVER_DIR)/RecPartAlgorithm
	rm -f $(SOLVER_DIR)/solution.txt $(SOLVER_DIR)/solution.mp $(SOLVER_DIR)/solution.svg
