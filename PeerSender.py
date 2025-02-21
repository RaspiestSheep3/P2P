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
    def __init__(self, signalingServerHost='127.0.0.1', signalingServerPort=12345, name=""):
        self.signalingServerHost = signalingServerHost
        self.signalingServerPort = signalingServerPort
        self.name = name
        self.peerSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # Initialize socket

    def getPublicIp(self):
        try:
            natType, externalIp, externalPort = stun.get_ip_info(stun_host = "stun.l.google.com",stun_port=19302)
            print(f"NAT Type: {natType}, Public IP: {externalIp}, Public Port: {externalPort}")
            return externalIp, externalPort, natType
        except Exception as e:
            print(f"STUN failed: {e}")
            return "0.0.0.0", 0, ""  # Default to local if STUN fails

    def connectToServer(self):
        try:
            print(f"Connecting to server at {self.signalingServerHost}:{self.signalingServerPort}")
            self.peerSocket.connect((self.signalingServerHost, self.signalingServerPort))

            # Setting up STUN
            print("SETTING UP STUN")
            self.publicIp, self.publicPort, self.natType = self.getPublicIp()

            # We are only sending files, so no need to register a listening port
            myInfo = {'ip': self.publicIp, 'port': self.publicPort, 'name': self.name, 'joinType': 'sender'}
            print(f"Sending peer info: {myInfo}")
            self.peerSocket.send(json.dumps(myInfo).encode())

            # Receive the list of known peers
            peers = self.peerSocket.recv(1024).decode()
            peers = json.loads(peers)  # Convert the JSON string into a Python dictionary

            self.peerSocket.close()
            return peers
        except Exception as e:
            print(f"Error connecting to server: {e}")
            return None  # Return None if connection fails

    def sendFiles(self, fileNames, peerIp, peerPort):
        peerSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            peerSocket.connect((peerIp, peerPort))

            # Send request to send files to peer
            peerSocket.send(json.dumps({"type": "sendRequestPing", "message": f"User {self.name} wishes to send files"}).encode())
            print("File transfer request sent to target listener")
            response = json.loads(peerSocket.recv(1024).decode())

            if response["type"] == "sendRequestPongAccept":
                # Permission granted to send files
                print("Permission granted to send files")
                for fileName in fileNames:
                    self.sendFile(peerIp, peerPort, fileName)
            else:
                print("File transfer request denied")
        except:
            print("File transfer request failed. Target listener might have disconnected")

        peerSocket.close()

    def sendFile(self, peerIp, peerPort, filePath):
        try:
            fileName = os.path.basename(filePath)
            fileSize = os.path.getsize(filePath)
            totalChunkCount = (fileSize // 1024) + (1 if fileSize % 1024 != 0 else 0)

            print(f"Sending file '{fileName}' ({fileSize} bytes) to {peerIp}:{peerPort}")

            peerSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            peerSocket.connect((peerIp, peerPort))

            # Send the filename
            peerSocket.send(fileName.encode().ljust(256))

            # Send total chunk count
            peerSocket.send(str(totalChunkCount).zfill(8).encode())

            # Encryption
            aesKey = os.urandom(32)
            publicKeyData = peerSocket.recv(2048)  # Receive full RSA key
            rsaKey = serialization.load_pem_public_key(publicKeyData)
            encryptedAesKey = rsaKey.encrypt(
                aesKey,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )

            peerSocket.send(len(encryptedAesKey).to_bytes(4, byteorder='big'))
            peerSocket.send(encryptedAesKey)

            with open(filePath, 'rb') as file:
                for chunkIndex in range(totalChunkCount):
                    chunk = file.read(1024)

                    # Encrypt chunk
                    iv = os.urandom(16)
                    cipher = Cipher(algorithms.AES(aesKey), modes.CBC(iv))
                    encryptor = cipher.encryptor()

                    padder = padding.PKCS7(128).padder()
                    chunk = padder.update(chunk) + padder.finalize()

                    encryptedData = encryptor.update(chunk) + encryptor.finalize()
                    encryptedChunk = iv + encryptedData

                    peerSocket.send(str(chunkIndex + 1).zfill(8).encode())  # Send chunk number
                    peerSocket.send(encryptedChunk)  # Send encrypted data
                    print(f"Sent chunk {chunkIndex + 1}/{totalChunkCount} ({1040} bytes)")

            print("File sent successfully!")
            peerSocket.close()
        except Exception as e:
            print(f"Error sending file: {e}")

def chooseTargetPort(peersItemsList):
    print("CONNECTED PEERS:")
    counter = 1
    for item in peersItemsList:
        key, itemDict = item  # Unpacking tuple properly
        suffix = ""
        if itemDict['name'] == deviceName:
            suffix = "(YOU)"

        print(f"{counter}. NAME: {itemDict['name']} PORT: {itemDict['port']} {suffix}")
        counter += 1

    targetPort = -2

    while targetPort == -2:
        try:
            targetPort = input("WHAT IS YOUR TARGET PORT? (Q to quit): ")
            if targetPort.strip().upper() == "Q":
                targetPort = -1
                continue
            targetPort = int(targetPort) - 1
            if peersItemsList[targetPort][1]['name'] == deviceName:
                print("INVALID: You cannot send a file to yourself.")
                targetPort = -2  # Reset to force re-selection
        except (IndexError, ValueError):
            print("INVALID INPUT. TRY AGAIN.")
            targetPort = -2  # Reset to force re-selection

    return targetPort


if __name__ == '__main__':
    peerCopy = PeerSender(name=deviceName)
    fileNames = []
    filePath = ""

    # Connect to signaling server and get peer list
    peers = peerCopy.connectToServer()

    if peers:  # Check if connection was successful
        # Uploading files
        root = tk.Tk()
        root.withdraw()  # Hide the main window
        files = filedialog.askopenfilenames(title="Select Files to Send")
        fileNames = list(files)

        targetPort = 0
        targetPeers = []
        while targetPort != -1:
            targetPort = chooseTargetPort(list(peers.items()))
            if targetPort == -1:
                break
            else:
                peerIp, peerInfo = list(peers.items())[targetPort]
                peerIp = peerInfo['ip']
                peerPort = peerInfo['port']

                # Avoid duplicates
                if not ([peerIp, peerPort] in targetPeers):
                    targetPeers.append([peerIp, peerPort])

        for targetPeer in targetPeers:
            print(f"TARGET PEER {targetPeer} {targetPeer[1]}")
            threading.Thread(target=peerCopy.sendFiles, args=(fileNames, targetPeer[0], targetPeer[1])).start()
    else:
        print("Failed to retrieve peers. Exiting.")
