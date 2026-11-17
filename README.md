# Golden

Golden is a private document workspace that helps you find documents matching rules you choose. It runs on your own Windows computer in a web browser.

## What you need

- A Windows 10 or Windows 11 computer.
- An internet connection for setup and for using a cloud AI service.
- Python 3.12. You only need to install Python once.
- An account and API key from an AI provider, if you want to use a cloud model. The provider may charge for use.

## First-time setup on Windows

1. Install **Python 3.12** from [python.org](https://www.python.org/downloads/windows/). During installation, check **Add python.exe to PATH**. Keep the **Python Launcher** option enabled.
2. Download this project from GitHub using the green **Code** button and **Download ZIP**. Unzip it somewhere you can find again, such as your Desktop. Do not move or rename files inside the unzipped folder.
3. Open the unzipped folder and double-click **`run_windows.bat`**.
4. The first run may take a few minutes while the program prepares itself. A black window will stay open while Golden is running; leave it open.
5. In your web browser, open **http://127.0.0.1:8000**.
6. Sign in with the starting username **admin** and password **admin**.

The script saves setup and application messages in **`windows-run.log`** in the project folder. If something goes wrong, look there for details. Do not share that file without checking it for private information first.

## Using Golden

1. Open **Settings → LLM connections**. Add a supported provider (OpenAI, Claude, Gemini, or local Ollama), choose a model, and enter its API key if it uses one. Select **Test connection** before continuing.
2. Open **Settings → Condition profiles** and write the things you want the app to look for. Put one condition on each line.
3. Create a **Scan profile**. Choose:
   - A folder containing the documents to check.
   - A different folder for results.
   - The AI connection and condition profiles to use.
   - A match threshold.
4. Select **Warm up** to list supported files. This step does not send documents to an AI service.
5. Select **Start** when you are ready for Golden to check the files. You can review each result and its report in the app.

Golden accepts PDF, JPG, and PNG files. A document must be no larger than 25 MB and contain no more than 40 pages. Password-protected PDFs are not accepted.

## Important privacy and cost information

- Golden runs on your computer and listens only on that computer. Keep the black window open while you use it.
- When you start a scan, the document text and, when needed, page images are sent to the AI provider you selected. Do not scan private documents unless you are comfortable with that provider receiving them.
- Your AI provider may charge you. Golden can show an estimate when you enter pricing, but the provider's bill is authoritative.
- Your settings, scan history, and encrypted API keys are kept in the **`data`** folder. Do not share or upload this folder. Keep it if you want to keep your history and settings.
- The default sign-in is `admin` / `admin`. This app is intended for use on your own computer, not as a public website.

## Stopping and starting later

- To stop Golden, close the black window (or press **Ctrl+C** in it).
- Next time, double-click **`run_windows.bat`** again and open **http://127.0.0.1:8000**.
- If you no longer need the app, you can delete the unzipped project folder. Keep or delete the `data` folder according to whether you want to keep its saved information.

## What is included in this project

The project is configured not to publish the separate `downloader` folder, local document folders, saved data, or downloaded documents. This README describes Golden, the document-processing app.

For a plain-language explanation of what happens during a scan, see [APP_LOGIC.md](./APP_LOGIC.md).
