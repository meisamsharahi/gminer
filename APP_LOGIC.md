# How Golden works

This note explains the app in everyday language. You do not need to read it to run Golden.

## The short version

You choose a folder of documents, tell Golden what matters, and choose an AI model. Golden checks each document against your conditions and gives you a report. A document is marked **Golden** only when its score is above the threshold you chose. Uncertain answers are marked for review instead of being treated as a match.

## What happens, step by step

1. **Connect an AI model.** In Settings, Golden saves the provider, model name, and (when needed) an encrypted API key on this computer. Testing the connection checks that the model can be reached; it does not send a document.
2. **Write conditions.** Each line is a separate rule. If a scan profile uses more than one condition profile, Golden combines all their rules. Each condition has the same weight.
3. **Choose folders and a threshold.** The input folder is where the original documents are. The output folder is where Golden writes its reports and copies documents that qualify as Golden.
4. **Warm up.** Golden looks through the input folder and lists PDF, JPG, and PNG files. It records file fingerprints so it can notice if a document changes. This step does not contact the AI model.
5. **Start the scan.** Golden reads each document. Text is used directly; pages with little or incomplete text may also be sent as images so a vision-capable model can inspect them. This is when document content is sent to the chosen provider and possible usage charges begin.
6. **Review the result.** The model reports each condition as met, not met, or uncertain, with explanations and page references. Golden checks the response and calculates the score. Uncertain results are sent for review. A passing document is copied to the output folder; a JSON report is saved for each attempt.

## Where information is kept

- **`data/`** — Golden's local database, settings, scan history, and encryption key for stored API keys.
- **Your chosen input folder** — Original documents are read but are not changed by Golden.
- **Your chosen output folder** — JSON reports and copies of Golden documents.
- **`windows-run.log`** — Setup and application messages that can help explain a problem.

Keep the `data` folder private and make a backup if you want to preserve your history. The encryption key is stored there too; without it, encrypted API keys cannot be recovered.

## Important limits

- Supported files: PDF, JPG, and PNG.
- Maximum input size: 25 MB per file.
- Maximum document length: 40 pages.
- Password-protected PDFs are not processed.
- The AI model can make mistakes. Read the report and verify important findings yourself.
- Cloud AI providers receive the document information needed for a scan and may charge for it. Check the provider's privacy terms and pricing.

## Why some files need another look

Golden marks a result **Needs review** if the model is unsure or if its answer cannot be safely matched to every condition. It does not count an uncertain answer as a positive match. Files that fail to process or whose reports could not be saved show an error status; the app offers retry actions where possible.
