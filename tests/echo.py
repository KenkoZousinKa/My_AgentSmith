import socket

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 8000))
    s.listen()
    while True:
        conn, addr = s.accept()
        with conn:
            data = conn.recv(4096)
            print(addr, data)
            conn.sendall(data)
