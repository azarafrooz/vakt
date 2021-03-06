PYTHON = python3
PIP = ${PYTHON} -m pip
PY_TEST = ${PYTHON} -m pytest


.PHONY: default
default: test lint

.PHONY: deps
deps:
	${PIP} install -e .[dev,mongo]

.PHONY: test
test:
	${PY_TEST}

.PHONY: test-ni
test-ni:
	${PY_TEST} -m "not integration"

.PHONY: test-i
test-i:
	${PY_TEST} -m "integration"

.PHONY: coverage
coverage:
	${PY_TEST} --cov-config .coveragerc --cov=./ --cov-report html:htmlcov

.PHONY: lint
lint:
	pylint vakt

.PHONY: release
release: test
	${PYTHON} setup.py sdist upload -r pypi

# runs mutation testing
.PHONY: mutation
mutation:
	${PIP} install mutmut
	mutmut run --runner="${PY_TEST}" --paths-to-mutate="vakt/" --dict-synonyms="Struct, NamedStruct"

.PHONY: mutation-report
mutation-report:
	@ruby -e '`mutmut results`.lines.select{ |i| i =~ /\d,/ }.join(",").split(","). \
			 map(&:strip).each { |f| puts " Survived ##{f}"; system "mutmut show #{f}" }'

.PHONY: bench
bench:
	${PYTHON} benchmark.py --checker regex --number 100000
	@echo "\n"
	${PYTHON} benchmark.py --checker rules --number 100000
