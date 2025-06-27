let images = {};
let bundles = {};
let notifications = [];
let unreadCount = 0;

// Load images from API
function loadImages() {
    fetch('/api/images')
    .then(res => res.json())
    .then(data => {
        images = data;
        updateImagesTable();
        updateBundleUI();
        updateImageCount();
    })
    .catch(err => {
        console.error('Error loading images:', err);
        document.getElementById('images-table-body').innerHTML = `
        <tr><td colspan="4" style="text-align: center; color: #ef4444; padding: 60px;">
            Error loading images. Please try again.
        </td></tr>
        `;
    });
}

function toggleNotifications() {
  const dropdown = document.getElementById('notification-dropdown');
  dropdown.classList.toggle('hidden');
  if (!dropdown.classList.contains('hidden')) {
    markAllNotificationsRead();
  }
}

function markAllNotificationsRead() {
  notifications.forEach(n => n.read = true);
  unreadCount = 0;
  updateNotificationUI();
}

function pollNotifications() {
  fetch('/api/notifications')
    .then(res => res.json())
    .then(data => {
      data.forEach(item => {
        const key = `${item.message}-${item.timestamp}`;
        if (!notifications.find(n => n.key === key)) {
          notifications.unshift({ ...item, key, read: false });
          unreadCount++;
        }
      });
      updateNotificationUI();
    });
}

function updateNotificationUI() {
  const badge = document.getElementById('notification-count');
  if (unreadCount > 0) {
    badge.classList.remove('hidden');
    badge.innerText = unreadCount;
  } else {
    badge.classList.add('hidden');
  }

  const list = document.getElementById('notification-list');
  list.innerHTML = notifications.map(n => `
    <li class="px-4 py-3 text-sm ${n.read ? 'text-gray-600' : 'font-semibold text-gray-800 bg-blue-50'}">
      <div class="flex justify-between">
        <span>${n.message}</span>
        <span class="text-xs text-gray-400">${n.timestamp}</span>
      </div>
    </li>
  `).join('');
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("notification-bell").addEventListener("click", toggleNotifications);
  pollNotifications();
  setInterval(pollNotifications, 10000);

  // Add event listener for clear button
  document.getElementById("clear-notifications").addEventListener("click", () => {
    fetch('/api/notifications/clear', {
      method: 'DELETE',
    })
    .then(res => {
      if (!res.ok) throw new Error("Failed to clear notifications");
      // Clear local data if server cleared successfully
      notifications.length = 0;
      unreadCount = 0;
      updateNotificationUI();
    })
    .catch(err => {
      console.error('Error clearing notifications:', err);
      alert('Failed to clear notifications.');
    });
  });  
});

function updateImageCount() {
  const count = Object.keys(images).length;
  document.getElementById('total-images').textContent = count;
}

function loadBundle(name) {
    const bundle = bundles[name];
    Object.entries(bundle).forEach(([imageName, tag]) => {
    const select = document.getElementById(`deploy-${imageName}`);
    if (select) select.value = tag;
    });
    showSection('deployments');
    alert(`Bundle "${name}" loaded successfully!`);
}

function loadBundles() {
    fetch('/api/bundles')
    .then(res => res.json())
    .then(data => {
        bundles = data;
        updateDeploymentBundles();
    })
    .catch(err => console.error('Failed to load bundles:', err));
}

function updateBundleUI() {
    const imageColors = ["bg-blue-500", "bg-green-500", "bg-red-500"];
    const selectors = document.getElementById('bundle-image-selectors');
    selectors.innerHTML = '';
  
    const storedTargets = JSON.parse(localStorage.getItem('deploymentTargets')) || [];
  
    Object.entries(images).forEach(([imageName, versions], index) => {
      const displayName = imageName.replace(/-/g, ' ');
      const latestVersion = versions[versions.length - 1];
  
      const versionOptions = versions.map(v => {
        const label = v === latestVersion ? `${v} (Latest)` : v;
        return `<option value="${v}">${label}</option>`;
      }).join('');
  
      const targetOptions = storedTargets.length > 0
        ? storedTargets.map(t => `<option value="${t.name}">${t.name}</option>`).join('')
        : '<option value="" disabled>No targets available</option>';
  
      selectors.innerHTML += `
        <div class="bg-gradient-to-br from-blue-50 to-blue-100 rounded-xl p-6 border border-blue-200 mb-4">
          <div class="flex items-center space-x-3 mb-4">
            <div class="w-10 h-10 ${imageColors[index % imageColors.length]} rounded-lg flex items-center justify-center">
              <svg class="w-5 h-5 text-white" fill="currentColor" viewBox="0 0 20 20">
                <path d="M3 4a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1V4zM3 10a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H4a1 1 0 01-1-1v-6zM14 9a1 1 0 00-1 1v6a1 1 0 001 1h2a1 1 0 001-1v-6a1 1 0 00-1-1h-2z"/>
              </svg>
            </div>
            <span class="font-semibold text-gray-800">${displayName}</span>
          </div>
  
          <select name="images[${imageName}]" class="w-full px-3 py-2 border border-blue-200 rounded-lg bg-white focus:ring-2 focus:ring-blue-500 focus:border-transparent">
            <option value="">Select version</option>
            ${versionOptions}
          </select>
  
          <select name="images[${imageName}]" class="w-full px-3 py-2 border border-blue-200 rounded-lg bg-white focus:ring-2 focus:ring-blue-500 focus:border-transparent mt-2">
            <option value="">Target Environment</option>
            ${targetOptions}
          </select>
        </div>
      `;
    });
  }
  

document.getElementById('save-bundle-btn').addEventListener('click',async () => {
    const bundleName = document.querySelector('input[name="name"]').value.trim();
    const bundleDescription = document.querySelector('textarea[name="description"]').value.trim();
    if (!bundleName || !bundleDescription) {
        alert("Bundle name and description are required.");
        return;
    }
    const existingBundlesRes = await fetch('/api/bundles'); // Adjust this to match your API
    const existingBundles = await existingBundlesRes.json();
    const nameExists = existingBundles.some(b => b.name.toLowerCase() === bundleName.toLowerCase());

    if (nameExists) {
        alert(`A bundle with the name "${bundleName}" already exists.`);
        return;
    }
    const selects = document.querySelectorAll('select[name^="images["]');

    const bundleImages = {}
    const errors = [];

    selects.forEach(select => {
        if (!select.value)
            return;
        const match = select.name.match(/images\[(.+?)\]/);
        if (!match) return;

        const imageName = match[1];
        const isEnvSelect = select.options[0].text === "Target Environment";


        if (!bundleImages[imageName]) bundleImages[imageName] = {};

        if (isEnvSelect) {
            bundleImages[imageName].env = select.value;
        } else {
            bundleImages[imageName].version = select.value;
        }
    });

    Object.entries(bundleImages).forEach(([image, config]) => {
        if ((config.env && !config.version)|(config.version && ! config.env)) {
            errors.push(`Image "${image}" should have both environment and version.`);
        }
    });
    
    if (errors.length > 0) {
        alert(errors.join("\n"));
        return;
    }
    
    const bundle = {
        name: bundleName,
        description: bundleDescription,
        images: bundleImages
    };
    console.log(bundle)
    fetch('/api/bundles', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(bundle)
    })
    .then(res => {
        if (!res.ok) {
        return res.text().then(text => {  // Get raw error page
            console.error("Server returned an error page:", text);
            throw new Error("Server error: " + res.status);
        });
        }
        return res.json();
    })
    .then(data => {
        console.log('Bundles:', data);
        alert("Bundle saved successfully");
    })
    .catch(err => {
        console.error("Failed to load bundles:", err);
    });
});



function updateImagesTable() {
    const tbody = document.getElementById('images-table-body');
    const imageEntries = Object.entries(images);
    
    if (imageEntries.length === 0) {
        tbody.innerHTML = `
            <tr><td colspan="4" style="text-align: center; color: #64748b; padding: 60px;">
            No images found in registry.
            </td></tr>
        `;
        return;
    }

    tbody.innerHTML = imageEntries.map(([imageName, tags]) => `
        <tr class="hover:bg-gray-50 transition-colors">
            <td class="px-6 py-4">
            <div class="flex items-center space-x-3">
                <div class="w-10 h-10 bg-green-100 rounded-lg flex items-center justify-center">
                <svg class="w-5 h-5 text-green-600" fill="currentColor" viewBox="0 0 20 20">
                    <path fill-rule="evenodd" d="M2 5a2 2 0 012-2h8a2 2 0 012 2v10a2 2 0 002 2H4a2 2 0 01-2-2V5zm3 1h6v4H5V6zm6 6H5v2h6v-2z" clip-rule="evenodd"/>
                </svg>
                </div>
                <div>
                <p class="font-semibold text-gray-800">${imageName}</p>
                </div>
            </div>
            </td>
            <td class="px-6 py-4 text-gray-600">${getImageDescription(imageName)}</td>
            <td class="px-6 py-4 w-56">
            <details class="cursor-pointer group">
                <summary class="text-blue-600 hover:text-blue-800 font-medium flex items-center space-x-1">
                <span>${tags.length} version${tags.length > 1 ? 's' : ''}</span>
                <svg class="w-4 h-4 transform group-open:rotate-180 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                </svg>
                </summary>
                <div class="mt-2 space-y-1">
                    ${tags.map((tag, idx) => `
                    <div class="${idx === 0 ? 'flex items-center gap-2 flex-wrap bg-gray-50 rounded-lg px-3 py-2' : 'text-sm text-gray-600 px-3 py-1'}">
                        <span class="text-sm font-mono">${tag}</span>
                        ${idx === 0 ? '<span class="status-badge">Latest</span>' : ''}
                    </div>
                    `).join('')}
                </div>
            </details>
            </td>
            <td class="px-6 py-4">
            <span class="status-badge">Active</span>
            </td>
        </tr>
        `).join('');
}

function getImageDescription(imageName) {
    const descriptions = {
        'backend-api': 'Backend API service for data processing',
        'frontend-app': 'Frontend application',
        'database': 'PostgreSQL database service',
        'nginx': 'Nginx web server and reverse proxy'
    };
    return descriptions[imageName] || 'Container image for deployment';
}

document.addEventListener('DOMContentLoaded', function() {
    const hash = window.location.hash || '#images';
    const activeLink = document.querySelector(`a[href="${hash}"]`);
    if (activeLink) {
        setActiveTab(activeLink);
    }
    loadImages();
    loadBundles();
    loadDeploymentFiles();
});

function triggerRollback(service, namespace) {
  if (!confirm(`Are you sure you want to rollback deployment '${service}' in namespace '${namespace}'?`)) {
    return;
  }

  fetch("/api/rollback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ service, namespace })
  })
  .then(res => res.json())
  .then(data => {
    if (data.message) {
      alert(data.message);
    } else {
      alert("Error: " + data.error);
    }
  })
  .catch(err => {
    console.error("Rollback failed:", err);
    alert("Unexpected error during rollback");
  });
}
function setActiveTab(element) {
    document.querySelectorAll('.nav-link').forEach(link => link.classList.remove('active'))
    element.classList.add('active');
}

window.addEventListener('hashchange', function() {
    const hash = window.location.hash;
    const activeLink = document.querySelector(`a[href="${hash}"]`);
    if (activeLink) {
    setActiveTab(activeLink);
    }
});

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('target-form');
    const nameInput = document.getElementById('target-name');
    const detailsInput = document.getElementById('target-details');
    const tableBody = document.getElementById('targets-table-body');
  
    const STORAGE_KEY = 'deploymentTargets';
    let targets = JSON.parse(localStorage.getItem(STORAGE_KEY)) || [];
  
    fetch("/api/running-deployments")
    .then(res => res.json())
    .then(data => {
      const cloudTbody = document.querySelector("#cloud-tbody");
  
      cloudTbody.innerHTML = "";


      data.forEach(deployment => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td class="px-6 py-4 font-mono text-gray-800">${deployment.service}</td>
          <td class="px-6 py-4 text-blue-700">${deployment.namespace}</td>
          <td class="px-6 py-4">${deployment.image_tag}</td>
          <td class="px-6 py-4 whitespace-nowrap">${deployment.replicas}</td>
          <td class="px-6 py-4">
            <button class="text-red-600 hover:text-red-800 font-semibold" onclick="triggerRollback('${deployment.service}', '${deployment.namespace}')">
              Rollback
            </button>
          </td>
        `;
        cloudTbody.appendChild(tr);
      });
    })
    .catch(err => console.error("Error loading deployments:", err));



    function saveTargets() {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(targets));
    }
  
    function renderTargets() {
      tableBody.innerHTML = '';
  
      if (targets.length === 0) {
        tableBody.innerHTML = `
          <tr>
            <td colspan="5" class="text-center text-gray-400 py-6">No deployment targets found.</td>
          </tr>
        `;
        return;
      }
  
      targets.forEach((target, index) => {
        const row = document.createElement('tr');
        row.className = 'hover:bg-gray-50 transition-colors';
  
        row.innerHTML = `
          <td class="px-6 py-4">
            <div class="flex items-center space-x-3">
              <div class="w-8 h-8 bg-blue-100 rounded-lg flex items-center justify-center">
                <span class="text-xs font-bold text-blue-600">${target.name.charAt(0).toUpperCase()}</span>
              </div>
              <span class="font-semibold text-gray-800">${target.name}</span>
            </div>
          </td>
          <td class="px-6 py-4 text-gray-600">${target.details}</td>
          <td class="px-6 py-4"><span class="status-badge">Active</span></td>
          <td class="px-6 py-4 text-sm text-gray-500">${target.created}</td>
          <td class="px-6 py-4 text-right">
            <button data-index="${index}" class="delete-target text-sm text-red-500 hover:text-red-700 font-medium">Delete</button>
          </td>
        `;
        tableBody.appendChild(row);
      });
  
      document.querySelectorAll('.delete-target').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const index = parseInt(e.target.dataset.index, 10);
          if (confirm(`Are you sure you want to delete "${targets[index].name}"?`)) {
            targets.splice(index, 1);
            saveTargets();
            renderTargets();
          }
        });
      });
    }
  
    form?.addEventListener('submit', (e) => {
      e.preventDefault();
  
      const name = nameInput.value.trim();
      const details = detailsInput.value.trim();
      if (!name || !details) {
        alert("Please fill in both name and description.");
        return;
      }
  
      const created = new Date().toISOString().split('T')[0];
      targets.push({ name, details, created });
      saveTargets();
      renderTargets();
      form.reset();
    });
  
    renderTargets();

    fetch("/api/namespaces")
      .then(res => res.json())
      .then(namespaces => {
        const select = document.getElementById("namespace-select");
        select.innerHTML = ""; // Clear loading message
        namespaces.forEach(ns => {
          const option = document.createElement("option");
          option.value = ns;
          option.textContent = ns;
          select.appendChild(option);
        });
      })
      .catch(err => {
        console.error("Failed to load namespaces:", err);
        const select = document.getElementById("namespace-select");
        select.innerHTML = `<option disabled>Error loading namespaces</option>`;
      });
  });
  
  function updateDeploymentBundles() {
    const container = document.getElementById('deployment-bundle-list');
    container.innerHTML = '';
  
    if (!bundles || Object.keys(bundles).length === 0) {
      container.innerHTML = `
        <div class="p-6 text-gray-500 text-center">
          No saved bundles found.
        </div>
      `;
      return;
    }
  
    Object.entries(bundles).forEach(([bundleName, bundle]) => {
        
      const {name='', description = '', images = {} } = bundle;
      // console.log(bundle);
  
      const imageList = Object.entries(images).map(([img, cfg]) => {
        const version = cfg.version || 'latest';
        const env = cfg.env ? ` (${cfg.env})` : '';
        return `<div class="text-sm text-gray-600">• ${img}:${version}${env}</div>`;
      }).join('');
  
      container.innerHTML += `
      <div class="p-6 hover:bg-gray-50 transition-colors">
        <div class="flex items-center justify-between">
          <div class="flex-1">
            <div class="flex items-center space-x-4 mb-3">
              <h5 class="text-lg font-semibold text-gray-800">${name}</h5>
              <span class="px-3 py-1 bg-gray-100 text-gray-800 rounded-full text-xs font-medium">Bundle</span>
            </div>
            <p class="text-gray-600 mb-4">${description}</p>
            <details class="cursor-pointer group">
              <summary class="text-blue-600 hover:text-blue-800 font-medium flex items-center space-x-2">
                <span>View Configuration</span>
                <svg class="w-4 h-4 transform group-open:rotate-180 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                </svg>
              </summary>
              <div class="mt-4 bg-gray-50 rounded-lg p-4 space-y-2">
                <div class="space-y-1">
                  <span class="text-sm font-medium text-gray-700">Images:</span>
                  <div class="pl-4 space-y-1">
                    ${imageList}
                  </div>
                </div>
              </div>
            </details>
          </div>
          <div class="ml-6 flex flex-col space-y-3">
            <button class="btn-success text-white px-6 py-2 rounded-xl font-medium flex items-center space-x-2" onclick="deployBundle('${name}')">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
              </svg>
              <span>Deploy</span>
            </button>
            <button class="text-red-600 hover:text-red-800 px-6 py-2 border border-red-300 rounded-xl font-medium" onclick="deleteBundle('${name}')">
              <svg class="w-5 h-5 mr-1 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
              </svg>
              Delete
            </button>
          </div>
        </div>
      </div>
    `;
    
    });
  }
  function deleteBundle(bundleName) {
    if (!confirm(`Are you sure you want to delete "${bundleName}"?`)) {
      return;
    }
  
    fetch(`/api/bundles/${encodeURIComponent(bundleName)}`, {
      method: 'DELETE'
    })
      .then(res => res.json())
      .then(data => {
        if (data.message) {
          alert(data.message);
          delete bundles[bundleName]; // remove locally
          updateDeploymentBundles();  // re-render UI
        } else {
          alert(data.error || "Failed to delete.");
        }
      })
      .catch(err => {
        console.error("Failed to delete bundle:", err);
        alert("Error deleting bundle.");
      });
  }

  document.getElementById('yaml-upload').addEventListener('change', function(event) {
    const file = event.target.files[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = function(e) {
        const text = e.target.result;
        document.getElementById('yaml-preview').textContent = text;
        document.getElementById('yaml-preview-container').classList.remove('hidden');
      };
      reader.readAsText(file);
    }
  });
function loadDeploymentFiles() {
  fetch('/api/deployment-files') 
    .then(res => res.json())
    .then(files => {
      const select = document.getElementById('deployment-file-select');
      files
        .filter(name => name.endsWith('.yaml'))
        .forEach(name => {
          const option = document.createElement('option');
          option.value = name;
          option.textContent = name;
          select.appendChild(option);
        });
    })
    .catch(err => {
      console.error('Failed to load deployment files', err);
    });
}

// document.getElementById('deployment-file-select').addEventListener('change', function () {
//   const selectedFile = this.value;
//   if (selectedFile) {
//     fetchDeploymentPreview(selectedFile);
//   }
// });

// function fetchDeploymentPreview(filename) {
//   fetch(`/api/deployment-files/${encodeURIComponent(filename)}`)
//     .then(res => {
//       if (!res.ok) {
//         throw new Error(`Failed to load ${filename}`);
//       }
//       return res.text(); // Assume it's plain YAML text
//     })
//     .then(content => {
//       displayPreview(content);
//     })
//     .catch(err => {
//       console.error('Error fetching deployment preview', err);
//       displayPreview('⚠️ Failed to load preview.');
//     });
// }
// function displayPreview(content) {
//   const preview = document.getElementById('deployment-preview');
//   preview.textContent = content;
// }


  function deployBundle(name) {
    let bundle = {}
    bundles.forEach((item)=> {
      if(item.name === name){
        bundle = item
      }
    })
    console.log(bundle)
    if (!bundle || !bundle.images) return;
  
    const namespace = document.getElementById('namespace-select')?.value || 'default';
    const strategy = document.getElementById('strategy-select')?.value || 'RollingUpdate';
    const selectedYamlFile = document.getElementById('deployment-file-select')?.value || null;

    if (!selectedYamlFile) {
      alert("Please select a deployment YAML file.");
      return;
    }

    const payload = {
      namespace: namespace,
      deployment_strategy: strategy,
      images: bundle.images,
      yaml_file: selectedYamlFile   
    };

    fetch('/api/deploy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        namespace: namespace,
        deployment_strategy: strategy,
        yaml_file: selectedYamlFile,
        images: bundle.images  // should include {version, target}  
      })
    })
    .then(res => res.json())
    .then(data => alert(data.message || "Deployment complete"))
    .catch(err => alert("Deployment failed"));
    console.log(payload);
    
  }
  
  
    