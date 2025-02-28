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
    def __init__(self, signaling_server_host='127.0.0.1', signaling_server_port=12345,name = ""):
        self.signaling_server_host = signaling_server_host
        self.signaling_server_port = signaling_server_port
        self.name = name
        self.peer_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # Start listening for file transfer before registering with the server
        self.listener_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener_socket.bind(('127.0.0.1', 0))  # OS assigns a free port
        self.listener_socket.listen(5) #Up to 5 qeued connections
        self.listen_port = self.listener_socket.getsockname()[1]

        #STUN - for public networks
        self.public_ip, self.public_port,self.natType = self.get_public_ip()
        print(f"Discovered Public IP: {self.public_ip}, Public Port: {self.public_port} NAT Type: {self.natType}")
        if(self.natType == ""):
            print("Some error occured. Do not run")
            exit()
        elif(self.natType == "Symmetric NAT"):
            print("You are using Symmetric NAT so we cannot use STUN. Unfortunately you cannot run this code")
            exit()
    
    def generate_rsa_keys(self):
        # Generate a 2048-bit RSA key pair
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048
        )
        
        # Serialize private key
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        )

        # Serialize public key
        public_key = private_key.public_key()
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        # Save keys to files
        with open("private_key.pem", "wb") as private_file:
            private_file.write(private_pem)
        
        with open("public_key.pem", "wb") as public_file:
            public_file.write(public_pem)

        return private_pem, public_pem
    
    def get_public_ip(self):
        try:
            nat_type, external_ip, external_port = stun.get_ip_info()
            print(f"NAT Type: {nat_type}, Public IP: {external_ip}, Public Port: {external_port}")
            return external_ip, external_port,nat_type
        except Exception as e:
            print(f"STUN failed: {e}")
            return "0.0.0.0", self.listen_port,""  # Default to local if STUN fails
      
    def connect_to_server(self):
        try:
            print(f"Connecting to server at {self.signaling_server_host}:{self.signaling_server_port}")
            self.peer_socket.connect((self.signaling_server_host, self.signaling_server_port))

            # Send peer info with dynamically assigned port
            my_info = {'ip': self.public_ip, 'port': self.public_port, 'name': self.name, 'join type': 'receiver'}
            print(f"Sending peer info: {my_info}")
            self.peer_socket.send(json.dumps(my_info).encode())

            # Receive the list of known peers
            peers = self.peer_socket.recv(1024).decode()
            print(f"Raw received peer list (string): {peers}")  # Debugging step

            peers = json.loads(peers)  # Convert the JSON string into a Python dictionary
            print(f"Processed peer list: {peers}")
            for peer in peers:
                print(f"Connected peers name : {(peers[peer])['name']}")

            self.peer_socket.close()
            return peers
        except Exception as e:
            print(f"Error connecting to server: {e}")
            
    def RequestChunk(self, targetChunk, pConnection):
        pConnection.send(str(targetChunk).zfill(8).encode()) 
        missingChunk = b""
        while len(missingChunk) < 1024:
            missingChunk += pConnection.recv(1024 - len(missingChunk)) 
        return missingChunk
        
    def DecryptAESKey(self, encrypted,privateRSA):
        return privateRSA.decrypt(
            encrypted,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
    
    def ReceiveFile(self, pConnection, file_name):
        file_name = file_name.strip()  # Read the 256-byte filename header
        print(f"Receiving file: {file_name}")
        file_name = file_name.split(".")
        file_name_end = file_name[1]
        file_name = file_name[0]
        
        file_name = f"{file_name}-Received.{file_name_end}"
        
        receivedChunks = []
        totalExpectedChunks = int(pConnection.recv(8).decode())
    
        #Send RSA public key for encryption
        with open("public_key.pem", "rb") as file:
            pConnection.send(file.read())
        
        # Open a file to save the incoming data with the correct name
        with open(file_name, 'wb') as file:
            fullData = [""] * totalExpectedChunks 

            #Encryption business
            key_length = int.from_bytes(pConnection.recv(4), byteorder='big')
            aesKeyEncrypted = pConnection.recv(key_length)
            privateRSAKey = ""
            with open("private_key.pem", "rb") as f:
                privateRSAKey = serialization.load_pem_private_key(f.read(), password=None)
            aesKey = self.DecryptAESKey(aesKeyEncrypted,privateRSAKey)
            
            while len(receivedChunks) < totalExpectedChunks:
                received = pConnection.recv(8).decode()  # Read chunk number
                chunkCount = int(received)

                
                chunk = b""
                while len(chunk) < 1040:
                    chunk += pConnection.recv(1040 - len(chunk)) 

                receivedChunks.append(chunkCount)
                fullData[chunkCount - 1] = chunk  # ✅ Correctly store received chunk
            
            print(f"CHUNK COUNT {len(receivedChunks)} EXPECTED {totalExpectedChunks}")
            if(len(receivedChunks) < totalExpectedChunks):
                #We have not received enough chunks
                lastChunk = 0
                for receivedChunk in receivedChunks:
                    if(receivedChunk -1 != lastChunk):
                        #Missing chunk
                        fullData[receivedChunk - 1] = self.RequestChunk(receivedChunk,pConnection)
                    lastChunk += 1
            else:
                pConnection.send("All files received".encode())
                print(f"File '{file_name}' received successfully!")
            
            #Writing data
            for dataPiece in fullData:
                
                #Decrpyting full data
                iv = dataPiece[:16]  # Extract IV
                encrypted_content = dataPiece[16:]  # Actual encrypted message

                cipher = Cipher(algorithms.AES(aesKey), modes.CBC(iv))
                decryptor = cipher.decryptor()
                decrypted_data = decryptor.update(encrypted_content) + decryptor.finalize()
                unpadder = padding.PKCS7(128).unpadder()
                decrypted_data = unpadder.update(decrypted_data) + unpadder.finalize()
                
                dataPiece =  decrypted_data.strip()  # Remove padding
                
                file.write(dataPiece)
            
        pConnection.close()

    def HandleConnection(self, pConnection):
        
        # Receive the filename 
        file_name = pConnection.recv(256).decode()
        
        try: #Try converting to a dictionary - if we can it is a ping not a file
            file_name = json.loads(file_name)
            if(file_name.get("type") == "heartbeat ping"):  #Ping from the server
                #We are responding
                response = json.dumps({"type": "hearbeat pong", "message": "I am still here!"}).encode()
                pConnection.send(response)
                pConnection.close()
    
            elif(file_name.get("type") == "send request ping"):
                print(file_name.get("message"))
                shouldAccept = input("Do you accept this file transfer request? (Y/N)? : ")
                if(shouldAccept.strip().upper() == "Y"):
                    response = json.dumps({"type": "send request pong - accept", "message": "I accept your file transfer"}).encode()
                    pConnection.send(response)
                else:
                    response = json.dumps({"type": "send request pong - deny", "message": "I do not accept your file transfer"}).encode()
                    pConnection.send(response)
            
        except json.JSONDecodeError: #If we cannot, we are recieving an actual file
            threading.Thread(target=self.ReceiveFile, args=(pConnection,file_name)).start()
        
        finally:
            return

    def listen_for_file(self):
        print(f"Listening for incoming file transfer on port {self.listen_port}...")

        while True:
            connection, address = self.listener_socket.accept()
            print(f"Connected to peer {address}")

            threading.Thread(target=self.HandleConnection,args=(connection,)).start()

if __name__ == '__main__':
    peer = PeerReceiver(name=deviceName)

    # Start listening in a separate thread so it doesn't block execution
    listen_thread = threading.Thread(target=peer.listen_for_file, daemon=True)
    listen_thread.start()

    #Generate Keys for encryption
    private_key, public_key = peer.generate_rsa_keys()
    
    # Connect to signaling server and get peer list
    peers = peer.connect_to_server()

    print("Peer is ready and waiting to receive a file...")

    # Keep the program running
    while waitingForFiles:
        pass  # Infinite loop to prevent the script from exiting