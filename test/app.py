from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename
import re
from packaging.version import Version  
from datetime import datetime
import subprocess
import requests
import yaml
import os
import json
import copy
import time




# Regular expression for semantic versions like 1.2.3
version_pattern = re.compile(r'^v?(\d+\.\d+(\.\d+)*)$')

app = Flask(__name__, template_folder='templates')
REGISTRY_URL = "http://cicd.ias.uni-stuttgart.de:5000"
DEPLOYMENT_YAML_PATH = "/tmp/flask-demo-latest.yaml"

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

from deployment_queue import load_queue

@app.route('/api/pending/<container_name>', methods=['GET'])
def get_pending_deployments(container_name):
    queue = load_queue()
    container_jobs = [item for item in queue if item['container'] == container_name]
    return jsonify(container_jobs), 200

from deployment_queue import remove_from_queue

@app.route('/api/clear_pending', methods=['POST'])
def clear_pending():
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    remove_from_queue(data)
    return jsonify({"status": "removed"}), 200


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

        from deployment_queue import add_to_queue

        def deploy_to_ugv(image_name, version, container, retries=3, delay=15):
            url = f"{UGV_SERVER_URL}/deploy"
            payload = {
                "container": container,
                "image": f"{REGISTRY_URL.replace('http://', '')}/{image_name}:{version}"
            }

            for attempt in range(retries):
                try:
                    print(f"Trying to deploy to {container} (attempt {attempt+1})...")
                    response = requests.post(url, json=payload, timeout=5)
                    if response.status_code == 200:
                        print(f"Deployment to {container} successful.")
                        return
                    else:
                        print(f"UGV responded with error: {response.status_code}, {response.text}")
                except requests.exceptions.RequestException:
                    print(f"{container} might be offline. Retrying in {delay} seconds...")

                time.sleep(delay)

            print(f"Saving failed deployment for {container} to queue.")
            add_to_queue(payload)


        UGV_GROUPS = {
            "UGV-Group1": ["ugv1", "ugv2"],
            "UGV-Group2": ["ugv3", "ugv4"],
            "UGV-Group3": ["ugv5"]
        }

        UGV_SERVER_URL = "http://129.69.81.194:5050"

        ugv_targets = {
            name: info["version"]
            for name, info in images.items()
            if info.get("env", "").startswith("UGV-Group")
        }

        for image_name, version in ugv_targets.items():
            group = images[image_name]["env"]
            containers = UGV_GROUPS.get(group, [])
            print(containers)

            for container_name in containers:
                try:
                    deploy_to_ugv(image_name, version, container_name)
                except Exception as e:
                    print(f"Failed to deploy {image_name}:{version} to {container_name}: {e}")

        

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
            print("dep",deployments)

        modified_deployments = []
        update_deployments = []

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
                update_deployments.append(deployment)
                continue

            metadata = deployment.setdefault("metadata", {})
            metadata["namespace"] = namespace

            if deployment.get("kind") != "Deployment":
                modified_deployments.append(deployment)
                if deployment.get("kind") != "Service":
                    update_deployments.append(deployment)
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

                stable_deployment["metadata"]["name"] = f"{base_name}"
                canary_deployment["metadata"]["name"] = f"{base_name}-canary"

                stable_deployment["spec"]["replicas"] = stable_replicas
                canary_deployment["spec"]["replicas"] = canary_replicas

                for d in (stable_deployment, canary_deployment):
                    d["spec"].setdefault("strategy", {})["type"] = "RollingUpdate"

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


            elif strategy.startswith("blue-green-stage"):
                stage_num = int(strategy.split("blue-green-stage")[-1])
                base_name = metadata["name"]

                # Find the matching Service from the full deployments list
                service = None
                for d in deployments:
                    if d.get("kind") == "Service" and d.get("metadata", {}).get("name") == base_name:
                        service = d
                        break

                
                # Create blue and green deployments
                blue_deployment = copy.deepcopy(deployment)
                green_deployment = copy.deepcopy(deployment)

                blue_deployment["metadata"]["name"] = f"{base_name}"
                green_deployment["metadata"]["name"] = f"{base_name}-green"

                blue_labels = blue_deployment["spec"]["template"].setdefault("metadata", {}).setdefault("labels", {})
                green_labels = green_deployment["spec"]["template"].setdefault("metadata", {}).setdefault("labels", {})

                blue_labels["version"] = "blue"
                green_labels["version"] = "green"

                blue_deployment["spec"]["selector"]["matchLabels"]["version"] = "blue"
                green_deployment["spec"]["selector"]["matchLabels"]["version"] = "green"

                # Update only green deployment containers
                update_container_images(green_deployment["spec"]["template"]["spec"]["containers"], image_lookup, label="BLUE-GREEN-GREEN")

                for d in (blue_deployment, green_deployment):
                    d["spec"].setdefault("strategy", {})["type"] = "RollingUpdate"

                if stage_num == 1:

                    # Modify existing Service selector to point to blue version (in place)
                    if service:
                        service["spec"]["selector"]["version"] = "blue"

                    else:
                        print(f"Service for {base_name} not found during blue-green stage 1")

                    # Append modified deployments and service to output
                    modified_deployments.extend([blue_deployment, green_deployment])

                elif stage_num == 2:

                    # Modify existing Service selector to point to blue version (in place)
                    if service:
                        service["spec"]["selector"]["version"] = "green"

                    else:
                        print(f"Service for {base_name} not found during blue-green stage 2")

                    # Append modified deployments and service to output
                    modified_deployments.extend([blue_deployment, copy.deepcopy(green_deployment)])

                    green_deployment["metadata"]["name"] = base_name
                    green_labels.pop("version", None)  #clean up
                    green_deployment["spec"]["selector"]["matchLabels"].pop("version",None) #clean up
                    service_copy = copy.deepcopy(service)
                    service_copy["spec"]["selector"].pop("version", None)
                    service_copy["metadata"]["namespace"]= namespace
                    update_deployments.extend([green_deployment, service_copy])

                else:
                    return jsonify({"message": f"Unsupported blue-green stage: {strategy}"}), 400

            else:
                return jsonify({"message": f"Unsupported deployment strategy: {strategy}"}), 400

        final_yaml_str = yaml.dump_all(modified_deployments, default_flow_style=False)
        update_yaml_str = yaml.dump_all(update_deployments, default_flow_style=False)
        print("Modified Deployment YAML:\n", final_yaml_str)

        # Determine file path
        if strategy in ["rolling-update", "recreate"] or strategy == "canary-stage4" :
            output_path = yaml_path  # overwrite original

        else:
            output_path = os.path.join("/tmp", f"modified_{yaml_file}")

        with open(output_path, 'w') as f:
            f.write(final_yaml_str)

        if strategy == "blue-green-stage2":
            with open(yaml_path, 'w') as f:
                f.write(update_yaml_str)

        print(f"Modified YAML saved to: {output_path}")

        # Apply the YAML to the cluster
        try:
            print(f"Applying YAML to cluster: {output_path}")
            result = subprocess.run(
                ["kubectl", "apply", "-f", output_path],
                capture_output=True, text=True, check=True
            )
            print("kubectl apply output:", result.stdout)
        except subprocess.CalledProcessError as e:
            print("kubectl apply error:", e.stderr)
            return jsonify({"error": "Failed to apply deployment YAML", "details": e.stderr}), 500


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
        data = request.get_json()
        service = data.get("service")
        namespace = data.get("namespace")
        if not service or not namespace:
            return jsonify({"error": "Missing service or namespace"}), 400

        result = subprocess.run(
            ['kubectl', 'rollout', 'undo', f'deployment/{service}', '--namespace', namespace],
            check=True, capture_output=True, text=True
        )
        return jsonify({"message": f"Rollback triggered successfully: {result.stdout.strip()}"}), 200

    except subprocess.CalledProcessError as e:
        return jsonify({"error": e.stderr.strip() if e.stderr else str(e)}), 500


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

@app.route('/api/running-deployments', methods=['GET'])
def running_deployments():
    try:
        result = subprocess.run(
            ["kubectl", "get", "deployments", "--all-namespaces", "-o", "json"],
            check=True,
            capture_output=True,
            text=True
        )
        deployments_json = json.loads(result.stdout)
        deployments = []
        for item in deployments_json.get("items", []):
            deployments.append({
                "service": item["metadata"]["name"],
                "namespace": item["metadata"]["namespace"],
                "image_tag": item["spec"]["template"]["spec"]["containers"][0]["image"].split(":")[-1],
                "replicas": item["spec"].get("replicas", 0),
            })
        return jsonify(deployments)
    except subprocess.CalledProcessError as e:
        return jsonify({"error": e.stderr}), 500



@app.route('/')
def index():
    return render_template('index_final.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
