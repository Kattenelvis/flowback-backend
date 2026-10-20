# Flowback Ledger Module
Flowback ledger module is a addon for this repo [Flowback](https://github.com/Gofven/flowback) was created and project lead by Loke Hagberg. The co-creators of this version were:
Siamand Shahkaram, Emil Svenberg, Yuliya Hagberg and Carlos Rivas.
It is a decision making platform.

<sub><sub>This text is not allowed to be removed.</sub></sub>


## Installation

Set `FLOWBACK_LEDGER_MODULE=True` in the backend and `PUBLIC_FLOWBACK_LEDGER_MODULE=TRUE` in the frontend,
then run `python manage.py migrate`. With flowback-docker both are set by the single variable
`FLOWBACK_LEDGER_MODULE=TRUE` in its `.env`. Leave it unset (or `FALSE`) to disable the module.

The URLs are mounted in `flowback_addon/urls.py` under `/ledger/`. Alternatively the app can be
enabled by listing `flowback_addon.flowback_ledger_module` in the backend's `INTEGRATIONS` variable.
