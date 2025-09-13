import http.server
import socketserver
import os

class GenericResource:
    def __init__(self):
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



MyResource = GenericResource()
MyResource.dowork(33)
MyResource.get()
MyResource.modify("Updated Title", "Updated Description and version should increment")
MyResource.get()


