from flask import Flask, jsonify, render_template, request
import re
from packaging.version import Version  
from datetime import datetime
import subprocess
import requests
import yaml
import os
import json
import copy



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

@app.route('/api/deployment-files', methods=['GET'])
def list_deployment_files():
    try:
        files = [f for f in os.listdir('/tmp/') if f.endswith('.yaml')]
        print(files)
        return jsonify(files)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
    try:
        data = request.get_json()
        print("Received deploy request data:", data)

        images = data.get("images", {})
        namespace = data.get("namespace")
        strategy = data.get("deployment_strategy", "rolling-update").lower()
        yaml_file = data.get("yaml_file")

        print(f"Namespace: {namespace}, Strategy: {strategy}, YAML file: {yaml_file}")

        # Filter server-targeted images
        server_images = {
            name: info["version"]
            for name, info in images.items()
            if info.get("env", "").lower() == "server"
        }

        if not server_images:
            return jsonify({"message": "No server-targeted images to deploy."}), 400

        containers = [
            {
                "name": name.replace("/", "-"),
                "image": f"{REGISTRY_URL.replace('http://', '')}/{name}:{tag}"
            }
            for name, tag in server_images.items()
        ]
        image_lookup = {c["name"]: c["image"] for c in containers}

        yaml_path = os.path.join("/tmp", yaml_file)
        if not os.path.isfile(yaml_path):
            return jsonify({"message": f"YAML file {yaml_file} not found on server."}), 400

        with open(yaml_path, 'r') as f:
            deployments = list(yaml.safe_load_all(f))

        modified_deployments = []

        def update_container_images(containers, image_lookup, label=""):
            for container in containers:
                name = container.get("name")
                if name in image_lookup:
                    old_image = container.get("image", "<none>")
                    container["image"] = image_lookup[name]
                    print(f"[{label}] Updated image for {name}: {old_image} → {container['image']}")

        for deployment in deployments:
            if not isinstance(deployment, dict):
                modified_deployments.append(deployment)
                continue

            metadata = deployment.setdefault("metadata", {})
            metadata["namespace"] = namespace

            if deployment.get("kind") != "Deployment":
                modified_deployments.append(deployment)
                continue

            pod_spec = deployment.setdefault("spec", {}) \
                                 .setdefault("template", {}) \
                                 .setdefault("spec", {})
            containers_spec = pod_spec.setdefault("containers", [])

            if strategy in ["rolling-update", "recreate"]:
                update_container_images(containers_spec, image_lookup, label=strategy.upper())

                deployment_strategy = deployment.setdefault("spec", {}).setdefault("strategy", {})
                deployment_strategy["type"] = "RollingUpdate" if strategy == "rolling-update" else "Recreate"

                modified_deployments.append(deployment)

            elif strategy.startswith("canary-stage"):
                print("entered canary")
                try:
                    stage_num = int(strategy.split("canary-stage")[-1])
                    if not (1 <= stage_num <= 4):
                        raise ValueError("Invalid stage")
                    stable_replicas = 4 - stage_num
                    canary_replicas = stage_num
                except ValueError:
                    return jsonify({"message": f"Invalid canary stage: {strategy}"}), 400

                base_name = metadata["name"]
                stable_deployment = copy.deepcopy(deployment)
                canary_deployment = copy.deepcopy(deployment)

                stable_deployment["metadata"]["name"] = f"{base_name}-stable"
                canary_deployment["metadata"]["name"] = f"{base_name}-canary"

                stable_deployment["spec"]["replicas"] = stable_replicas
                canary_deployment["spec"]["replicas"] = canary_replicas

                # Label pods
                stable_labels = stable_deployment["spec"]["template"].setdefault("metadata", {}).setdefault("labels", {})
                canary_labels = canary_deployment["spec"]["template"].setdefault("metadata", {}).setdefault("labels", {})
                stable_labels["version"] = "stable"
                canary_labels["version"] = "canary"

                # Only update canary container images
                canary_containers = canary_deployment["spec"]["template"]["spec"]["containers"]
                update_container_images(canary_containers, image_lookup, label=f"CANARY-{stage_num}")

                if stage_num < 4:
                    modified_deployments.extend([stable_deployment, canary_deployment])
                else:
                    # At stage 4: only write canary deployment, rename it back to original
                    canary_deployment["metadata"]["name"] = base_name
                    canary_labels.pop("version", None)  #clean up
                    modified_deployments.append(canary_deployment)

            else:
                return jsonify({"message": f"Unsupported deployment strategy: {strategy}"}), 400

        final_yaml_str = yaml.dump_all(modified_deployments, default_flow_style=False)
        print("Modified Deployment YAML:\n", final_yaml_str)

        # Determine file path
        if strategy in ["rolling-update", "recreate"] or strategy == "canary-stage4":
            output_path = yaml_path  # overwrite original
        else:
            output_path = os.path.join("/tmp", f"modified_{yaml_file}")

        with open(output_path, 'w') as f:
            f.write(final_yaml_str)
        print(f"Modified YAML saved to: {output_path}")

        return jsonify({
            "message": "Deployment YAML modified successfully",
            "strategy": strategy,
            "containers": containers
        }), 200

    except Exception as e:
        print("Error during deployment:", e)
        return jsonify({"error": str(e)}), 500


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
