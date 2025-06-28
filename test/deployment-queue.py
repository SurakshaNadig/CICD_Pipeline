import json
import os

QUEUE_FILE = 'deployment_queue.json'

def load_queue():
    if not os.path.exists(QUEUE_FILE):
        return []
    with open(QUEUE_FILE, 'r') as f:
        return json.load(f)

def save_queue(queue):
    with open(QUEUE_FILE, 'w') as f:
        json.dump(queue, f, indent=2)

def add_to_queue(item):
    queue = load_queue()
    queue.append(item)
    save_queue(queue)

def remove_from_queue(item):
    queue = load_queue()
    queue = [q for q in queue if q != item]
    save_queue(queue)
