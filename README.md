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

## CLI
    python client.py upload report.pdf mypassword
    python client.py download <file_id> report.pdf.mhc      # encrypted
    python client.py decrypt report.pdf.mhc mypassword
