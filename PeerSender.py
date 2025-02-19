import socket
import json
import os
import threading
import tkinter as tk
from tkinter import filedialog

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

    def SendFiles(self, pFileNames, peerIP, peerPort):
        peer_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            peer_socket.connect((peerIP, peerPort))
            
            #Send request to send files to peer
            peer_socket.send(json.dumps({"type": "send request ping", "message": f"User {self.name} wishes to send files"}).encode())
            print("We have sent a file transfer request to target listener")
            response = json.loads(peer_socket.recv(1024).decode())

            if(response["type"] == "send request pong - accept"):
                #We can send a file
                print("WE CAN SEND FILES")
                for fileName in pFileNames:
                    self.send_file(peerIP, peerPort, fileName)
            else:
                print("WE CANNOT SEND FILES")
        except:
            print("File transfer request failed. It is likely target listener has disconnected")
        
        peer_socket.close()
    
    def send_file(self, pPeer_ip, pPeer_port, pFile_path):
        try:
            file_name = os.path.basename(pFile_path)  # Extract the filename
            file_size = os.path.getsize(pFile_path)
            print(f"Sending file '{file_name}' of size {file_size} bytes to {pPeer_ip}:{pPeer_port}")

            peer_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            peer_socket.connect((pPeer_ip, pPeer_port))
            
            # Send the filename first
            peer_socket.send(file_name.encode().ljust(256))  # Send a 256-byte filename header

            # Send the actual file data
            with open(pFile_path, 'rb') as file:
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

    targetPort = -2
    
    while targetPort == -2:
        try:
            targetPort = input("WHAT IS YOUR TARGET PORT? (Q to quit): ")
            if(targetPort.strip().upper() == "Q"):
                targetPort = -1
                continue
            targetPort = int(targetPort) - 1
            if peersItemsList[targetPort][1]['name'] == deviceName:  # FIXED: Properly accessing the dictionary
                print("INVALID: You cannot send a file to yourself.")
                targetPort = -2  # Reset to force re-selection
        except (IndexError, ValueError):
            print("INVALID INPUT. TRY AGAIN.")
            targetPort = -2  # Reset to force re-selection
        
    return targetPort


if __name__ == '__main__':
    peer_copy = PeerSender(name=deviceName)
    fileNames = []
    file_path = ""

    # Connect to signaling server and get peer list
    peers = peer_copy.connect_to_server()
    
    if peers:  # FIXED: Check if connection was successful
        # Get the first peer's IP and port
        #print(f"PEERS ITEMS {list(peers.items())}")

        # Send a file to the first peer
        #Uploading files
        root = tk.Tk()
        root.withdraw()  # Hide the main window
        files = filedialog.askopenfilenames(title="Select Files to Send")
        fileNames = list(files)
        
        targetPort = 0
        targetPeers = []
        while(targetPort != -1):
            targetPort = ChooseTargetPort(list(peers.items()))
            if(targetPort == -1):
                break
            else:
                peer_ip, peer_info = list(peers.items())[targetPort]
                peer_ip = peer_info['ip']
                peer_port = peer_info['port']
            
                #Avoid duplicates
                if not([peer_ip,peer_port] in targetPeers):
                    targetPeers.append([peer_ip,peer_port])
           
        for targetPeer in targetPeers:
            print(f"TARGET PEER {targetPeer} {targetPeer[1]}") 
            threading.Thread(target=peer_copy.SendFiles, args=(fileNames, targetPeer[0], targetPeer[1])).start()
    else:
        print("Failed to retrieve peers. Exiting.")