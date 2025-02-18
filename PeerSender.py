import socket
import json
import os


deviceName = "DEVICE 1"

class PeerSender:
    def __init__(self, signaling_server_host='127.0.0.1', signaling_server_port=12345, name=""):
        self.signaling_server_host = signaling_server_host
        self.signaling_server_port = signaling_server_port
        self.name = name
        self.peer_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # FIXED: Initialize socket

    def connect_to_server(self):
        try:
            print(f"Connecting to server at {self.signaling_server_host}:{self.signaling_server_port}")
            self.peer_socket.connect((self.signaling_server_host, self.signaling_server_port))

            # We are only sending files, so no need to register a listening port
            my_info = {'ip': '127.0.0.1', 'port': 0, 'name' : self.name, 'join type': 'sender'}  # FIXED: We don't need to listen
            print(f"Sending peer info: {my_info}")
            self.peer_socket.send(json.dumps(my_info).encode())

            # Receive the list of known peers
            peers = self.peer_socket.recv(1024).decode()
            #print(f"Raw received peer list (string): {peers}")  # Debugging step
            
            peers = json.loads(peers)  # Convert the JSON string into a Python dictionary
            #print(f"Processed peer list: {peers}")

            self.peer_socket.close()
            return peers
        except Exception as e:
            print(f"Error connecting to server: {e}")
            return None  # FIXED: Return None if connection fails

    def send_file(self, peer_ip, peer_port, file_path):
        try:
            file_name = os.path.basename(file_path)  # Extract the filename
            file_size = os.path.getsize(file_path)
            print(f"Sending file '{file_name}' of size {file_size} bytes to {peer_ip}:{peer_port}")

            peer_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            peer_socket.connect((peer_ip, peer_port))

            # Send the filename first
            peer_socket.send(file_name.encode().ljust(256))  # Send a 256-byte filename header

            # Send the actual file data
            with open(file_path, 'rb') as file:
                while chunk := file.read(1024):
                    peer_socket.send(chunk)

            print("File sent successfully!")
            peer_socket.close()
        except Exception as e:
            print(f"Error sending file: {e}")

def ChooseTargetPort(peersItemsList):
    print("CONNECTED PEERS: ")
    counter = 1
    for item in peersItemsList:
        key, itemDict = item  # FIXED: Unpacking tuple properly
        suffix = ""
        if itemDict['name'] == deviceName:
            suffix = "(YOU)"
        
        print(f"{counter}. NAME : {itemDict['name']} PORT : {itemDict['port']} {suffix}")
        counter += 1

    targetPort = -1
    
    while targetPort == -1:
        try:
            targetPort = int(input("WHAT IS YOUR TARGET PORT? : ")) - 1
            if peersItemsList[targetPort][1]['name'] == deviceName:  # FIXED: Properly accessing the dictionary
                print("INVALID: You cannot send a file to yourself.")
                targetPort = -1  # Reset to force re-selection
        except (IndexError, ValueError):
            print("INVALID INPUT. TRY AGAIN.")
            targetPort = -1  # Reset to force re-selection
        
    return targetPort


if __name__ == '__main__':
    peer_copy = PeerSender(name=deviceName)

    # Connect to signaling server and get peer list
    peers = peer_copy.connect_to_server()
    
    if peers:  # FIXED: Check if connection was successful
        # Get the first peer's IP and port
        #print(f"PEERS ITEMS {list(peers.items())}")
        
        peer_ip, peer_info = list(peers.items())[ChooseTargetPort(list(peers.items()))]
        peer_ip = peer_info['ip']
        peer_port = peer_info['port']

        # Send a file to the first peer
        file_path = input("What is the name of the file you wish to send? : ")
        peer_copy.send_file(peer_ip, peer_port, file_path)
    else:
        print("Failed to retrieve peers. Exiting.")