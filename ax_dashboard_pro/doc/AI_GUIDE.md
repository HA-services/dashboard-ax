# AI assistant guide

## Configure

Settings, AI provider. Choose **OpenAI compatible** (any server that speaks the chat completions API) or **Anthropic**. Enter base URL, API key and model name. The key is stored as a system parameter readable only by administrators.

## Use

- **Generate a dashboard**: on a dashboard, press Generate with AI. Describe what you want ("sales by salesperson and monthly revenue for this year"). Optionally limit the models and keywords the assistant may focus on. The assistant proposes items. Review and confirm.
- **Explain**: from an item menu choose Explain with AI to get a short reading of the numbers. Available on KPI, chart and list items.

## What is sent to the provider

For generation: the prompt you type and a catalog of model and field names. For Explain: what the item currently shows, that is the KPI values, up to 30 chart labels and values, or for list items the column names and up to 15 visible rows. List rows are record level, so do not use Explain on lists containing data you cannot send to your provider. If that is not acceptable, leave AI unconfigured. All other features work without it.

## Limits

The assistant only proposes items. It never runs SQL, never writes records, and generated items are normal items subject to your access rights. Output quality depends on the provider and model you choose.
