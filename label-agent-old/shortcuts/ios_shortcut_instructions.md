# iOS Shortcut: "Scan to Label Agent"
1) Actions:
   - **Take Photo** (Rear camera, 1 photo)
   - **Choose from Menu**
       - Prompt: "What are you scanning?"
       - Items: "Comic", "Card"
   - **If Result == Comic**
       - **Get Contents of URL**
           - Method: POST
           - URL: `https://YOUR_DOMAIN/ingest`
           - Request Body: Form
               - image: (Magic Variable) Photo
               - type: comic
       - **Show Result**
   - **Otherwise**
       - **Get Contents of URL**
           - Method: POST
           - URL: `https://YOUR_DOMAIN/ingest`
           - Request Body: Form
               - image: (Magic Variable) Photo
               - type: card
       - **Show Result**

2) Replace `YOUR_DOMAIN` with your public server or LAN IP if testing locally (e.g., http://192.168.1.23:8080).

3) For Android, use "HTTP Shortcuts" with the same multipart form.
