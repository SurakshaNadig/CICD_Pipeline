from flask import Flask, request, jsonify, render_template
import requests
import subprocess
import yaml

app = Flask(__name__)

EVENTS = []
REGISTRY_URL = "http://cicd.ias.uni-stuttgart.de:5000"
DEPLOYMENT_YAML_PATH = "/tmp/flask-demo-latest.yaml"  # path to existing file
DEPLOYMENT_NAME = "flask-demo-latest"
NAMESPACE = "flask-app"

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/notify', methods=['POST'])
def notify():
    data = request.get_json()
    for event in data.get("events", []):
        if event.get("action") == "push":
            repo = event["target"]["repository"]
            tag = event["target"].get("tag", "latest")
            EVENTS.append({"repo": repo, "tag": tag})
    return '', 200

@app.route('/api/events')
def get_events():
    return jsonify(EVENTS)

@app.route('/api/images')
def list_images():
    resp = requests.get(f"{REGISTRY_URL}/v2/_catalog")
    return jsonify(resp.json())

@app.route('/api/tags/<repository>')
def list_tags(repository):
    resp = requests.get(f"{REGISTRY_URL}/v2/{repository}/tags/list")
    return jsonify(resp.json())

@app.route('/deploy', methods=['POST'])
def deploy_image():
    data = request.get_json()
    image = data.get("image")
    tag = data.get("tag")

    if not image or not tag:
        return jsonify({"error": "Missing image or tag"}), 400

    image_ref = f"cicd.ias.uni-stuttgart.de:5000/{image}:{tag}"

    # Load and modify existing YAML
    with open(DEPLOYMENT_YAML_PATH, 'r') as f:
        deployment = yaml.safe_load(f)

    deployment['spec']['template']['spec']['containers'][0]['image'] = image_ref

    # Write updated YAML
    with open(DEPLOYMENT_YAML_PATH, 'w') as f:
        yaml.dump(deployment, f)

    # Apply updated deployment
    try:
        subprocess.run(['kubectl', 'apply', '-f', DEPLOYMENT_YAML_PATH],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Force rollout to refresh pods
        subprocess.run(['kubectl', 'rollout', 'restart', f'deployment/{DEPLOYMENT_NAME}', '-n', NAMESPACE],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        return jsonify({"message": f"Deployment updated and restarted with image {image_ref}"})
    except subprocess.CalledProcessError as e:
        return jsonify({"error": e.stderr.decode()}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)

