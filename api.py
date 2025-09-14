from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import urllib.parse
import uuid


class GenericResource:
    def __init__(self):
        self.id = str(uuid.uuid4())
        self.version = 0
        self.state = "Stopped"
        self.title = "Default Title"
        self.description = "Default Description"
        self.processing_results = 0

    def get(self):
        print("Version: " + str(self.version))
        print("State: " + self.state)
        print("Title: " + self.title)
        print("Description " + self.description)
        print("Processing results (ignore if 0): " + str(self.processing_results))

    def modify(self, title_input, description_input):
        # Logically could be updated
        if self.title != title_input and self.description != description_input:
            self.title = title_input
            self.description = description_input
            self.version += 1
        else:
            return

    def dowork(self, n):
        self.state = "Processing"
        self.processing_results = self.processing(n)
        self.state = "Complete"

    # 44 takes about 1 minutes 45 seconds to complete. 31 is very quick / near instant.
    def processing(self, n):
        if n >= 45:
            print("Number too large, not enough processing power. Pass an int less than 45.")
            return
        elif n <= 1:
            return n
        else:
            return self.processing(n - 1) + self.processing(n - 2)
        
    def to_dict(self):
        return {
            "id": self.id,
            "version": self.version,
            "state": self.state,
            "title": self.title,
            "description": self.description,
            "processing_results:": self.processing_results
        }


class HTTPRequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/create':
            try:
                new_instance = GenericResource()
                instances[new_instance.id] = new_instance

                self.send_response(201)
                self.send_header('Content-type', 'application/json')
                self.end_headers()

                response = {
                    "Message": "GenericResource created!",
                    "id": str(new_instance.id)
                }

                self.wfile.write(json.dumps(response).encode('utf-8'))
            except json.JSONDecodeError:
                self.send_error(400, "Invalid JSON")
            except Exception as e:
                self.send_error(500, f"Internal Server Error: " + str(e))
        else:
            self.send_error(404, "Path not found")

    def do_GET(self):
        # List
        if self.path == '/instances':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            if instances:
                response = {
                    "instances" : [instance.to_dict() for instance in instances.values()],
                    "count": len(instances)
                }
                self.wfile.write(json.dumps(response).encode('utf-8'))
            else:
                response = {
                    "instances" : "None",
                    "count": len(instances)
                }
                self.wfile.write(json.dumps(response).encode('utf-8'))

        # Get
        elif self.path.startswith('/instances/'):
            parsed_id = self.path[len('/instances/'):]

            try:
                if parsed_id in instances:
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()

                    response = {
                        "instance": instances[parsed_id].to_dict()
                    }
                    self.wfile.write(json.dumps(response).encode('utf-8'))
                else:
                    self.send_error(404, f"Instance with ID {parsed_id} not found")
            except ValueError:
                self.send_error(400, "Invalid instance ID format")
            except Exception as e:
                self.send_error(500, f"Internal Server Error: " + str(e))
            
        else:
            self.send_error(404, "Path not found")

    def do_DELETE(self):
        if self.path.startswith('/instances/'):
            parsed_id = self.path[len('/instances/'):]

            try:
                if parsed_id in instances:
                    del instances[parsed_id]

                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()

                    response = {
                        "message": "Instance " + parsed_id + " has been deleted!"
                    }
                    self.wfile.write(json.dumps(response).encode('utf-8'))
                else:
                    self.send_error(404, f"Instance with ID {parsed_id} not found")
            except Exception as e:
                self.send_error(500, f"Internal Server Error: " + str(e))



instances = {}

server_address = ('', 8081)
httpd = HTTPServer(server_address, HTTPRequestHandler)
print(f"Server running on http://localhost:8081")
print("POST to /create to create new instances")
print("GET /instances to list all instances") 
print("GET /instances/<id> to get specific instance")
httpd.serve_forever()