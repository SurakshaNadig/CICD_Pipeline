from flask import Flask, jsonify, render_template, request
import re
from packaging.version import Version  # 
from datetime import datetime
import subprocess
import requests
import yaml
import os
import json


# Regular expression for semantic versions like 1.2.3
version_pattern = re.compile(r'^v?(\d+\.\d+(\.\d+)*)$')

app = Flask(__name__, template_folder='templates')
REGISTRY_URL = "http://cicd.ias.uni-stuttgart.de:5000"
DEPLOYMENT_YAML_PATH = "/tmp/flask-demo-latest.yaml"
DEPLOYMENT_NAME = "flask-demo-latest"

BUNDLES_FILE = "bundles.json"
NOTIFICATIONS_FILE = "notification.json"


def is_valid_version(tag):
    return tag.lower() == "latest" or version_pattern.match(tag)

def safe_version_key(tag):
    try:
        return Version(tag.lstrip('v'))
    except:
        return Version("0.0.0")  # Push "latest" to the bottom or top, depending on order

def load_bundles():
    if os.path.exists(BUNDLES_FILE):
        with open(BUNDLES_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_bundles(bundles):
    with open(BUNDLES_FILE, 'w') as f:
        json.dump(bundles, f)

def load_notifications():
    if os.path.exists(NOTIFICATIONS_FILE):
        with open(NOTIFICATIONS_FILE, 'r') as f:
            return json.load(f)
    return []

def save_notifications(notifications):
    with open(NOTIFICATIONS_FILE, 'w') as f:
        json.dump(notifications, f)

@app.route('/api/notifications/clear', methods=['DELETE'])
def clear_notifications():
    save_notifications([])  # Save an empty list
    return jsonify({"message": "All notifications cleared."}), 200

@app.route('/api/images')
def get_images():
    try:
        catalog = requests.get(f"{REGISTRY_URL}/v2/_catalog", verify=False)
        catalog.raise_for_status()
        repositories = catalog.json().get("repositories", [])

        result = {}
        for repo in repositories:
            tags_resp = requests.get(f"{REGISTRY_URL}/v2/{repo}/tags/list", verify=False)
            if tags_resp.status_code == 200:
                tags = tags_resp.json().get("tags", [])
                if tags:
                    valid_tags = [tag for tag in tags if is_valid_version(tag)]
                    sorted_tags = sorted(valid_tags, key=safe_version_key, reverse=True)
                    result[repo] = sorted_tags  

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/deploy', methods=['POST'])
def deploy():
    data = request.get_json()
    print("Received deploy request data:", data)

    images = data.get("images", {})
    namespace = data.get("namespace")
    strategy = data.get("deployment_strategy", "rolling-update").lower()
    print("Namespace:", namespace)
    print("Strategy:", strategy)
    print("All images:", images)

    server_images = {
        name: info["version"]
        for name, info in images.items()
        if info.get("env", "").lower() == "server"
    }
    print("Filtered server-targeted images:", server_images)

    if not server_images:
        print("No server-targeted images found. Aborting deploy.")
        return jsonify({"message": "No Server-targeted images to deploy."})

    containers = [
        {
            "name": name.replace("/", "-"),
            "image": f"{REGISTRY_URL.replace('http://', '')}/{name}:{tag}"
        }
        for name, tag in server_images.items()
    ]
    print("Prepared containers for deployment:", containers)

    # --- Actual deployment logic below ---

    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": DEPLOYMENT_NAME,
            "namespace": namespace
        },
        "spec": {
            "replicas": 1,
            "selector": {
                "matchLabels": {
                    "app": DEPLOYMENT_NAME
                }
            },
            "template": {
                "metadata": {
                    "labels": {
                        "app": DEPLOYMENT_NAME
                    }
                },
                "spec": {
                    "containers": containers
                }
            }
        }
    }

    try:
        with open(DEPLOYMENT_YAML_PATH, 'w') as f:
            yaml.dump(deployment, f)
        print("Deployment YAML written to:", DEPLOYMENT_YAML_PATH)

        subprocess.run(['kubectl', 'apply', '-f', DEPLOYMENT_YAML_PATH, '--namespace', namespace], check=True)
        subprocess.run(['kubectl', 'rollout', 'restart', f'deployment/{DEPLOYMENT_NAME}', '--namespace', namespace], check=True)

        return jsonify({"message": "Deployment applied and restarted successfully."})
    except subprocess.CalledProcessError as e:
        return jsonify({"error": e.stderr.decode() if e.stderr else str(e)}), 500


    # containers = [
    #     {
    #         "name": name.replace("/", "-"),
    #         "image": f"{REGISTRY_URL.replace('http://', '')}/{name}:{tag}"
    #     }
    #     for name, tag in server_images.items()
    # ]

    # deployment = {
    #     "apiVersion": "apps/v1",
    #     "kind": "Deployment",
    #     "metadata": {
    #         "name": DEPLOYMENT_NAME
    #     },
    #     "spec": {
    #         "replicas": 1,
    #         "selector": {
    #             "matchLabels": {
    #                 "app": DEPLOYMENT_NAME
    #             }
    #         },
    #         "template": {
    #             "metadata": {
    #                 "labels": {
    #                     "app": DEPLOYMENT_NAME
    #                 }
    #             },
    #             "spec": {
    #                 "containers": containers
    #             }
    #         }
    #     }
    # }

    # # Kubernetes native strategies
    # if strategy == "rolling-update":
    #     deployment["spec"]["strategy"] = {
    #         "type": "RollingUpdate",
    #         "rollingUpdate": {
    #             "maxSurge": "25%",
    #             "maxUnavailable": "25%"
    #         }
    #     }

    # elif strategy == "recreate":
    #     deployment["spec"]["strategy"] = {
    #         "type": "Recreate"
    #     }

    # # For blue-green, canary, a-b-testing — custom logic follows
    # try:
    #     with open(DEPLOYMENT_YAML_PATH, 'w') as f:
    #         yaml.dump(deployment, f)

    #     if strategy == "rolling-update" or strategy == "recreate":
    #         subprocess.run(['kubectl', 'apply', '-f', DEPLOYMENT_YAML_PATH, '--namespace', namespace], check=True)
    #         subprocess.run(['kubectl', 'rollout', 'restart', f'deployment/{DEPLOYMENT_NAME}', '--namespace', namespace], check=True)
    #         return jsonify({"message": f"{strategy} deployment completed."})

    #     elif strategy == "blue-green":
    #         # 1. Deploy new deployment (e.g. with suffix '-green')
    #         green_deployment_name = DEPLOYMENT_NAME + "-green"
    #         deployment["metadata"]["name"] = green_deployment_name
    #         deployment["spec"]["selector"]["matchLabels"]["app"] = green_deployment_name
    #         deployment["spec"]["template"]["metadata"]["labels"]["app"] = green_deployment_name

    #         with open(DEPLOYMENT_YAML_PATH, 'w') as f:
    #             yaml.dump(deployment, f)

    #         subprocess.run(['kubectl', 'apply', '-f', DEPLOYMENT_YAML_PATH, '--namespace', namespace], check=True)

    #         # 2. Switch traffic (typically involves Service switching label selectors)
    #         # For simplicity, restart Service selector to green deployment here
    #         service_patch = {
    #             "spec": {
    #                 "selector": {
    #                     "app": green_deployment_name
    #                 }
    #             }
    #         }
    #         patch_file = "service-patch.yaml"
    #         with open(patch_file, 'w') as f:
    #             yaml.dump(service_patch, f)

    #         subprocess.run(['kubectl', 'patch', 'service', DEPLOYMENT_NAME, '-n', namespace, '--patch-file', patch_file], check=True)

    #         return jsonify({"message": "Blue-green deployment applied and traffic switched."})

    #     elif strategy == "canary" or strategy == "a-b-testing":
    #         # Simplified example for Canary / A-B Testing
    #         # Real A-B requires ingress or service mesh setup - here we do basic rollout with less replicas

    #         deployment["spec"]["replicas"] = 2
    #         deployment["spec"]["strategy"] = {
    #             "type": "RollingUpdate",
    #             "rollingUpdate": {
    #                 "maxSurge": 1,
    #                 "maxUnavailable": 1
    #             }
    #         }

    #         with open(DEPLOYMENT_YAML_PATH, 'w') as f:
    #             yaml.dump(deployment, f)

    #         subprocess.run(['kubectl', 'apply', '-f', DEPLOYMENT_YAML_PATH, '--namespace', namespace], check=True)

    #         # Add annotations or labels for canary/A-B if you want (extend here)

    #         return jsonify({"message": f"{strategy.capitalize()} deployment applied with canary style."})

    #     else:
    #         return jsonify({"error": f"Unknown deployment strategy '{strategy}'."}), 400

    # except subprocess.CalledProcessError as e:
    #     return jsonify({"error": e.stderr}), 500


# @app.route('/api/deploy', methods=['POST'])
# def deploy():
#     data = request.get_json()
#     images = data.get("images", {})

#     containers = []
#     for name, tag in images.items():
#         containers.append({
#             "name": name.replace("/", "-"),
#             "image": f"{REGISTRY_URL.replace('http://', '').replace('http://', '')}/{name}:{tag}"
#         })

#     deployment = {
#         "apiVersion": "apps/v1",
#         "kind": "Deployment",
#         "metadata": {
#             "name": DEPLOYMENT_NAME
#         },
#         "spec": {
#             "replicas": 1,
#             "selector": {
#                 "matchLabels": {
#                     "app": DEPLOYMENT_NAME
#                 }
#             },
#             "template": {
#                 "metadata": {
#                     "labels": {
#                         "app": DEPLOYMENT_NAME
#                     }
#                 },
#                 "spec": {
#                     "containers": containers
#                 }
#             }
#         }
#     }

#     try:
#         with open(DEPLOYMENT_YAML_PATH, 'w') as f:
#             yaml.dump(deployment, f)

#         subprocess.run(['kubectl', 'apply', '-f', DEPLOYMENT_YAML_PATH, '--namespace', NAMESPACE], check=True)
#         subprocess.run(['kubectl', 'rollout', 'restart', f'deployment/{DEPLOYMENT_NAME}', '--namespace', NAMESPACE], check=True)

#         return jsonify({"message": "Deployment applied and restarted successfully."})
#     except subprocess.CalledProcessError as e:
#         return jsonify({"error": e.stderr.decode()}), 500

@app.route('/api/rollback', methods=['POST'])
def rollback():
    try:
        subprocess.run(['kubectl', 'rollout', 'undo', f'deployment/{DEPLOYMENT_NAME}', '--namespace', NAMESPACE], check=True)
        return jsonify({"message": "Rollback triggered successfully."})
    except subprocess.CalledProcessError as e:
        return jsonify({"error": e.stderr.decode()}), 500

@app.route('/api/bundles', methods=['GET'])
def api_get_bundles():
    bundles = load_bundles()
    return jsonify(bundles)

@app.route('/api/bundles', methods=['POST'])
def api_save_bundles():
    data = request.get_json()
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Invalid bundle data"}), 400

    bundles = load_bundles()
    if not isinstance(bundles, list):
        bundles = []

    bundles.append(data)
    save_bundles(bundles)

    return jsonify({"message": "Bundle saved", "bundle": data})


@app.route('/api/notifications', methods=['GET'])
def api_get_notifications():
    notifications = load_notifications()
    return jsonify(notifications)

@app.route('/notify', methods=['POST'])
def notify():
    data = request.get_json()
    if not data or 'image' not in data or 'tag' not in data:
        return jsonify({"error": "Missing image or tag"}), 400
    notifications = load_notifications()


    notifications.append({
        "message": f"New image pushed: {data['image']}:{data['tag']}",
        "timestamp": datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    })

    # notifications.append({"image": data['image'], "tag": data['tag']})
    save_notifications(notifications)
    return jsonify({"message": "Notification stored"})

@app.route('/api/bundles/<name>', methods=['DELETE'])
def api_delete_bundle(name):
    name = name.strip()
    bundles = load_bundles()
    print("Loaded bundles (list format):", bundles)

    index_to_delete = None
    for i, b in enumerate(bundles):
        if b.get("name") == name:
            index_to_delete = i
            break

    if index_to_delete is None:
        return jsonify({"error": f"Bundle '{name}' not found"}), 404

    deleted = bundles.pop(index_to_delete)
    save_bundles(bundles)
    return jsonify({"message": f"Bundle '{deleted['name']}' deleted successfully."})
    
@app.route('/api/namespaces', methods=['GET'])
def list_namespaces():
    try:
        result = subprocess.run(
            ["kubectl", "get", "namespaces", "-o", "json"],
            check=True,
            capture_output=True,
            text=True
        )
        ns_json = json.loads(result.stdout)
        namespaces = [item['metadata']['name'] for item in ns_json['items']]
        return jsonify(namespaces), 200

    except subprocess.CalledProcessError as e:
        return jsonify({"error": f"Failed to get namespaces: {e}"}), 500

@app.route('/')
def index():
    return render_template('index_final.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
