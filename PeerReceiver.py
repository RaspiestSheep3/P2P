import socket
import json
import threading
from datetime import datetime
import stun
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

waitingForFiles = True
deviceName = datetime.now().strftime("%H:%M:%S")

class PeerReceiver:
    def __init__(self, signalingServerHost='xyz', signalingServerPort=12345, name=""):
        self.signalingServerHost = signalingServerHost
        self.signalingServerPort = signalingServerPort
        self.name = name
        self.peerSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # Start listening for file transfer before registering with the server
        self.listenerSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listenerSocket.bind(('xyz', 0))  # OS assigns a free port
        self.listenerSocket.listen(5)  # Up to 5 queued connections
        self.listenPort = self.listenerSocket.getsockname()[1]

        # STUN - for public networks
        print("LISTENING FOR STUN")
        self.publicIp, self.publicPort, self.natType = self.getPublicIp()
        print(f"Discovered Public IP: {self.publicIp}, Public Port: {self.publicPort} NAT Type: {self.natType}")
        if self.natType == "":
            print("Some error occurred. Do not run")
            exit()
        elif self.natType == "Symmetric NAT":
            print("You are using Symmetric NAT so we cannot use STUN. Unfortunately, you cannot run this code")
            exit()

    def generateRsaKeys(self):
        # Generate a 2048-bit RSA key pair
        privateKey = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048
        )

        # Serialize private key
        privatePem = privateKey.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        )

        # Serialize public key
        publicKey = privateKey.public_key()
        publicPem = publicKey.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        # Save keys to files
        with open("privateKey.pem", "wb") as privateFile:
            privateFile.write(privatePem)

        with open("publicKey.pem", "wb") as publicFile:
            publicFile.write(publicPem)

        return privatePem, publicPem

    def getPublicIp(self):
        try:
            natType, externalIp, externalPort = stun.get_ip_info(stun_host = "stun.l.google.com",stun_port=19302)
            print(f"NAT Type: {natType}, Public IP: {externalIp}, Public Port: {externalPort}")
            return externalIp, externalPort, natType
        except Exception as e:
            print(f"STUN failed: {e}")
            return "0.0.0.0", self.listenPort, ""  # Default to local if STUN fails

    def connectToServer(self):
        try:
            print(f"Connecting to server at {self.signalingServerHost}:{self.signalingServerPort}")
            self.peerSocket.connect((self.signalingServerHost, self.signalingServerPort))

            # Send peer info with dynamically assigned port
            myInfo = {'ip': self.publicIp, 'port': self.publicPort, 'name': self.name, 'joinType': 'receiver'}
            print(f"Sending peer info: {myInfo}")
            self.peerSocket.send(json.dumps(myInfo).encode())

            # Receive the list of known peers
            peers = self.peerSocket.recv(1024).decode()
            print(f"Raw received peer list (string): {peers}")  # Debugging step

            peers = json.loads(peers)  # Convert the JSON string into a Python dictionary
            print(f"Processed peer list: {peers}")
            for peer in peers:
                print(f"Connected peer's name: {(peers[peer])['name']}")

            self.peerSocket.close()
            return peers
        except Exception as e:
            print(f"Error connecting to server: {e}")

    def requestChunk(self, targetChunk, peerConnection):
        peerConnection.send(str(targetChunk).zfill(8).encode())
        missingChunk = b""
        while len(missingChunk) < 1024:
            missingChunk += peerConnection.recv(1024 - len(missingChunk))
        return missingChunk

    def decryptAesKey(self, encrypted, privateRsa):
        return privateRsa.decrypt(
            encrypted,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

    def receiveFile(self, peerConnection, fileName):
        fileName = fileName.strip()  # Read the 256-byte filename header
        print(f"Receiving file: {fileName}")
        fileNameParts = fileName.split(".")
        fileNameEnd = fileNameParts[1]
        fileName = fileNameParts[0]
        fileName = f"{fileName}-Received.{fileNameEnd}"

        receivedChunks = []
        totalExpectedChunks = int(peerConnection.recv(8).decode())

        # Send RSA public key for encryption
        with open("publicKey.pem", "rb") as file:
            peerConnection.send(file.read())

        # Open a file to save the incoming data with the correct name
        with open(fileName, 'wb') as file:
            fullData = [""] * totalExpectedChunks

            # Encryption business
            keyLength = int.from_bytes(peerConnection.recv(4), byteorder='big')
            aesKeyEncrypted = peerConnection.recv(keyLength)
            with open("privateKey.pem", "rb") as f:
                privateRsaKey = serialization.load_pem_private_key(f.read(), password=None)
            aesKey = self.decryptAesKey(aesKeyEncrypted, privateRsaKey)

            while len(receivedChunks) < totalExpectedChunks:
                received = peerConnection.recv(8).decode()  # Read chunk number
                chunkCount = int(received)

                chunk = b""
                while len(chunk) < 1040:
                    chunk += peerConnection.recv(1040 - len(chunk))

                receivedChunks.append(chunkCount)
                fullData[chunkCount - 1] = chunk  # ✅ Correctly store received chunk

            print(f"CHUNK COUNT {len(receivedChunks)} EXPECTED {totalExpectedChunks}")
            if len(receivedChunks) < totalExpectedChunks:
                # We have not received enough chunks
                lastChunk = 0
                for receivedChunk in receivedChunks:
                    if receivedChunk - 1 != lastChunk:
                        # Missing chunk
                        fullData[receivedChunk - 1] = self.requestChunk(receivedChunk, peerConnection)
                    lastChunk += 1
            else:
                peerConnection.send("All files received".encode())
                print(f"File '{fileName}' received successfully!")

            # Writing data
            for dataPiece in fullData:
                # Decrypting full data
                iv = dataPiece[:16]  # Extract IV
                encryptedContent = dataPiece[16:]  # Actual encrypted message

                cipher = Cipher(algorithms.AES(aesKey), modes.CBC(iv))
                decryptor = cipher.decryptor()
                decryptedData = decryptor.update(encryptedContent) + decryptor.finalize()
                unpadder = padding.PKCS7(128).unpadder()
                decryptedData = unpadder.update(decryptedData) + unpadder.finalize()

                dataPiece = decryptedData.strip()  # Remove padding
                file.write(dataPiece)

        peerConnection.close()

    def handleConnection(self, peerConnection):
        # Receive the filename
        fileName = peerConnection.recv(256).decode()

        try:
            # Try converting to a dictionary - if we can it is a ping not a file
            fileName = json.loads(fileName)
            if fileName.get("type") == "heartbeatPing":  # Ping from the server
                # We are responding
                response = json.dumps({"type": "heartbeatPong", "message": "I am still here!"}).encode()
                print("SENDING HEARTBEAT PONG")
                peerConnection.send(response)
                peerConnection.close()

            elif fileName.get("type") == "sendRequestPing":
                print(fileName.get("message"))
                shouldAccept = input("Do you accept this file transfer request? (Y/N)? : ")
                if shouldAccept.strip().upper() == "Y":
                    response = json.dumps({"type": "sendRequestPongAccept", "message": "I accept your file transfer"}).encode()
                    peerConnection.send(response)
                else:
                    response = json.dumps({"type": "sendRequestPongDeny", "message": "I do not accept your file transfer"}).encode()
                    peerConnection.send(response)

        except json.JSONDecodeError:  # If we cannot, we are receiving an actual file
            threading.Thread(target=self.receiveFile, args=(peerConnection, fileName)).start()

        finally:
            return

    def listenForFile(self):
        print(f"Listening for incoming file transfer on port {self.listenPort}...")

        while True:
            connection, address = self.listenerSocket.accept()
            print(f"Connected to peer {address}")

            threading.Thread(target=self.handleConnection, args=(connection,)).start()


if __name__ == '__main__':
    peer = PeerReceiver(name=deviceName)

    # Start listening in a separate thread so it doesn't block execution
    listenThread = threading.Thread(target=peer.listenForFile, daemon=True)
    listenThread.start()

    # Generate Keys for encryption
    privateKey, publicKey = peer.generateRsaKeys()

    # Connect to signaling server and get peer list
    peers = peer.connectToServer()

    print("Peer is ready and waiting to receive a file...")

    # Keep the program running
    while waitingForFiles:
        pass  # Infinite loop to prevent the script from exiting
