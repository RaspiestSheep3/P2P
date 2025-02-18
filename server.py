import socket
import json
import threading
import select
import time

# Signaling server class
class SignalingServer:
    def __init__(self, host='127.0.0.1', port=12345):
        self.host = host
        self.port = port
        self.peers = {}
        self.lock = threading.Lock()  # Lock to ensure thread safety for shared data
        self.timeBetweenHeartbeats = 10

    def handle_peer(self, peer_socket):
        try:
            print("Waiting to receive peer info...")  # Debug message
            peer_info = peer_socket.recv(1024).decode()
            if not peer_info:
                print("No data received from peer, returning...")
                return

            print(f"Received peer info: {peer_info}")  # Debug message
            peer_info = json.loads(peer_info)

            peer_ip = peer_info['ip']
            peer_port = peer_info['port']
            print(f"New peer connected: {peer_ip}:{peer_port}")

            # Store peer info in a thread-safe manner
            with self.lock:
                self.peers[f"{peer_ip}:{peer_port}"] = peer_info

            # Send the updated peers list to the connecting peer
            with self.lock:
                peer_socket.send(json.dumps(self.peers).encode())

            print(f"Current peers list: {self.peers}")  # Debug message
            
        except Exception as e:
            print(f"Error handling peer: {e}")
        finally:
            peer_socket.close()

    def RemoveFromPeers(self, ipPortCode):
        for peer in self.peers:
            if(peer == ipPortCode):
                del self.peers[ipPortCode]
                break

    def CheckPeersConnected(self):
        while True:
            time.sleep(self.timeBetweenHeartbeats)
            print(f"PEERS {self.peers}")
            #Ping each peer 
            
            peersToRemove = []
            for peer in self.peers:
                
                connectionSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                peerIP = self.peers[peer]["ip"]
                peerPort = self.peers[peer]["port"]
                
                #Only send to receiver types
                if(self.peers[peer]["join type"] != "receiver"):
                    continue
                
                try:
                    connectionSocket.connect((peerIP,peerPort)) 
                    
                    #Sending each peer a ping to see if they are still contactable
                    pingMessage = json.dumps({"type": "heartbeat ping", "message": "Are you still there?"}).encode()
                    connectionSocket.send(pingMessage)
                    
                    #Receiving a response
                    response = connectionSocket.recv(1024).decode()
                    
                    if(response):
                        #Likely peer is still connected
                        print(f"{self.peers[peer]['name']} is still connected")
                        connectionSocket.close()
                    else:
                        #Possible they have disconnected
                        print("No response received. Peer may be disconnected.")
                        connectionSocket.close()
                        peersToRemove.append(peer)
                except:
                    connectionSocket.close()
                    print("Connection failed. It is likely peer has disconnected")
                    peersToRemove.append(peer)
            
            for peerToRemove in peersToRemove:
                self.RemoveFromPeers(peerToRemove)

    def start(self):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.bind((self.host, self.port))
        server_socket.listen(5)
        print(f"Signaling server running on {self.host}:{self.port}")

        #Pinging each peer to check theyre connected
        threading.Thread(target=self.CheckPeersConnected, args=()).start()
        
        while True:
            print("Waiting for peer connections...")
            peer_socket, addr = server_socket.accept()
            print(f"New connection from {addr}")

            # Handle each peer in a separate thread
            threading.Thread(target=self.handle_peer, args=(peer_socket,)).start()
            

if __name__ == '__main__':
    server = SignalingServer()
    server.start()
