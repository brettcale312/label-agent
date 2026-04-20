import argparse, httpx, mimetypes, os

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', required=True, help='Path to image (jpg/png)')
    ap.add_argument('--type', required=True, choices=['card', 'comic'])
    ap.add_argument('--host', default='http://localhost:8080', help='API host')
    args = ap.parse_args()

    url = f"{args.host}/ingest"
    mime = mimetypes.guess_type(args.file)[0] or 'application/octet-stream'
    files = {'image': (os.path.basename(args.file), open(args.file, 'rb'), mime)}
    data = {'type': args.type}

    with httpx.Client(timeout=30.0) as client:
        r = client.post(url, files=files, data=data)
        print(r.status_code, r.text)

if __name__ == '__main__':
    main()
