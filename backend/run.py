"""Start the API with safe local defaults and explicit deployed authentication."""
import argparse
import uvicorn

from app.config import settings
from app.security import validate_runtime_settings

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8000)
    args = parser.parse_args()
    validate_runtime_settings()
    if args.host not in {'127.0.0.1','localhost','::1'} and not settings.auth_enabled:
        parser.error('External binding requires AUTH_ENABLED=true. Keep local mode on127.0.0.1.')
    uvicorn.run('app.main:app',host=args.host,port=args.port,proxy_headers=False)
