import os
import uvicorn
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    is_prod = os.getenv("ENV", "dev").lower() in ("prod", "production")

    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0" if is_prod else "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        workers=int(os.getenv("WORKERS", "4")) if is_prod else 1,
        reload=not is_prod,
        access_log=is_prod,
        proxy_headers=is_prod,
        forwarded_allow_ips="*" if is_prod else None,
        log_level=os.getenv("LOG_LEVEL", "info" if is_prod else "debug"),
    )
