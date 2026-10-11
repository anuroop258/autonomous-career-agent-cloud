# Start the connected web app

1. Extract the project to a short path such as `C:\job_agent`.
2. Make sure Node.js and Python are installed.
3. Start Chrome CDP sessions as usual for the platform you want to run.
4. From the project root, run:

```powershell
py -m pip install -r webapp\backend\requirements.txt
py -m uvicorn webapp.backend.main:app --host 127.0.0.1 --port 8000
```

5. In another terminal:

```powershell
cd webapp\frontend
npm install
npm run dev
```

Open `http://localhost:5175`.

The UI starts the existing `main.py` platform agents; it does not replace them.
