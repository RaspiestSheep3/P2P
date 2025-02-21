import socket 
import json
import os
import threading
import tkinter as tk
from tkinter import filedialog
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
import stun

deviceName = "DEVICE 1"

class PeerSender:
    def __init__(self, signaling_server_host='127.0.0.1', signaling_server_port=12345, name=""):
        self.signaling_server_host = signaling_server_host
        self.signaling_server_port = signaling_server_port
        self.name = name
        self.peer_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # FIXED: Initialize socket

    def get_public_ip(self):
        try:
            nat_type, external_ip, external_port = stun.get_ip_info()
            print(f"NAT Type: {nat_type}, Public IP: {external_ip}, Public Port: {external_port}")
            return external_ip, external_port,nat_type
        except Exception as e:
            print(f"STUN failed: {e}")
            return "0.0.0.0", 0,""  # Default to local if STUN fails

    def connect_to_server(self):
        try:
            print(f"Connecting to server at {self.signaling_server_host}:{self.signaling_server_port}")
            self.peer_socket.connect((self.signaling_server_host, self.signaling_server_port))

            #Setting up STUN
            
            self.public_ip, self.public_port,self.natType = self.get_public_ip()
        
            # We are only sending files, so no need to register a listening port
            my_info = {'ip': self.public_ip, 'port': self.public_port, 'name' : self.name, 'join type': 'sender'}  # FIXED: We don't need to listen
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
            file_name = os.path.basename(pFile_path)
            file_size = os.path.getsize(pFile_path)
            totalChunkCount = (file_size // 1024) + (1 if file_size % 1024 != 0 else 0)

            print(f"Sending file '{file_name}' ({file_size} bytes) to {pPeer_ip}:{pPeer_port}")

            peer_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            peer_socket.connect((pPeer_ip, pPeer_port))

            # Send the filename
            peer_socket.send(file_name.encode().ljust(256))

            # Send total chunk count
            peer_socket.send(str(totalChunkCount).zfill(8).encode())

            #Encryption
            aes_key = os.urandom(32)
            public_key_data = peer_socket.recv(2048) #Full rsa data
            rsaKey = serialization.load_pem_public_key(public_key_data)
            encryptedAESKey = rsaKey.encrypt(
                aes_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )

            chunkedData = []
            peer_socket.send(len(encryptedAESKey).to_bytes(4, byteorder='big'))
            peer_socket.send(encryptedAESKey)
            with open(pFile_path, 'rb') as file:
                for chunkIndex in range(totalChunkCount):
                    chunk = file.read(1024)
                    
                    #Encrypt chunk
                    iv = os.urandom(16)
                    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv))
                    encryptor = cipher.encryptor()
                    
                    padder = padding.PKCS7(128).padder()
                    chunk = padder.update(chunk) + padder.finalize()
                    
                    encrypted_data = encryptor.update(chunk) + encryptor.finalize()
                    encrypted_chunk = iv + encrypted_data
                    
                    # ✅ Ensure last chunk is sent correctly (Fix 3)
                    #chunkSize = min(1040, file_size - (chunkIndex * 1040))  
                    #chunk = chunk[:chunkSize]  # ✅ Trim excess bytes for last chunk

                    peer_socket.send(str(chunkIndex + 1).zfill(8).encode())  # Send chunk number
                    peer_socket.send(encrypted_chunk)  # Send only required bytes
                    chunkedData.append(chunk)
                    print(f"Sent chunk {chunkIndex + 1}/{totalChunkCount} ({1040} bytes)")

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