"""Run locally: python run.py  =>  http://127.0.0.1:8000"""
import uvicorn

if __name__ == "__main__":
    print("\nUsahaInsight siap dijalankan di http://127.0.0.1:8000\n")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)

