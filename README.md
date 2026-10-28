# VaultGrid — encrypted, replicated storage over LAN

Cloud Controller (NameNode) + DataNodes. Files are split into blocks, each block is AES-256-GCM
encrypted, replicated on multiple DataNodes, and can be downloaded in encrypted form. VaultGrid
monitors node health and can re-replicate blocks when a DataNode returns online.

## Run (one PC demo)
    pip install -r requirements.txt
    python demo.py                 # automated proof: upload, kill node, recover, decrypt
    # or manually:
    python datanode.py 6001 & python datanode.py 6002 & python datanode.py 6003 &
    python namenode.py             # open http://127.0.0.1:5000

## Run on the lab LAN (real cloud)
On each lab PC:   python datanode.py 6001
On controller PC: python namenode.py --datanodes http://192.168.1.11:6001 http://192.168.1.12:6001 http://192.168.1.13:6001
Students use the web dashboard from any browser on the LAN: http://<controller-ip>:5000

## Deploy on Render
The repository includes a Render Blueprint in `render.yaml`. In Render, create a new Blueprint
from this GitHub repository and set `VAULTGRID_AUTH_USERNAME` and `VAULTGRID_AUTH_PASSWORD` as
private environment variables when prompted. Use unique, strong credentials; never commit them.
Render serves the app over HTTPS and the controller requires HTTP Basic authentication when
those variables are configured. The Render start script refuses to start without both values.

The Blueprint uses Render's free web-service plan and does not attach a persistent disk.
Uploaded files and metadata are temporary and can be lost whenever the service restarts,
sleeps, or redeploys; use disposable test files only. It starts the controller and three
DataNodes inside one service, so replicas are not independent-node redundancy. For persistent
storage, use a paid instance with a persistent disk and check Render's current pricing. The
dashboard submits decrypt passwords in a POST body. Older clients may still use the legacy GET
query parameter, which should not be used for public deployments.

## CLI
    python client.py upload report.pdf mypassword
    python client.py download <file_id> report.pdf.mhc      # encrypted
    python client.py decrypt report.pdf.mhc mypassword
