import * as THREE from "../vendor/three.module.js";
import { OrbitControls } from "../vendor/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "../vendor/jsm/loaders/GLTFLoader.js";
import { FBXLoader } from "../vendor/jsm/loaders/FBXLoader.js";

/* -------------------------------------------------------------------------- */
/* Skinned 3D preview                                                         */
/* -------------------------------------------------------------------------- */

const DISPOSE_EVENT = "soundisle:preview-dispose";

function formatOf(track) {
  const format = String(track?.format || "").toLowerCase();
  if (format) return format;
  const name = String(track?.filename || "");
  return name.includes(".") ? name.split(".").pop().toLowerCase() : "";
}

function disposeObject(root) {
  root.traverse((child) => {
    if (child.geometry) child.geometry.dispose();
    const materials = Array.isArray(child.material) ? child.material : child.material ? [child.material] : [];
    for (const material of materials) {
      for (const value of Object.values(material)) {
        if (value && value.isTexture) value.dispose();
      }
      material.dispose();
    }
  });
}

function setStatus(root, text, bad = false) {
  root.querySelectorAll("[data-skin-status]").forEach((node) => {
    node.textContent = text;
    node.classList.toggle("is-bad", bad);
  });
}

function number(value, digits = 2) {
  return Number(value).toFixed(digits).replace(/\.?0+$/, "");
}

export function mountSkinPreview(container, track) {
  const canvasHost = container.querySelector("[data-skin-canvas]");
  const animationSelect = container.querySelector("[data-skin-animation]");
  const wireToggle = container.querySelector("[data-skin-wire]");
  const screenshotButton = container.querySelector("[data-skin-shot]");
  const resetButton = container.querySelector("[data-skin-reset]");
  const metaNode = container.querySelector("[data-skin-meta]");
  const materialsNode = container.querySelector("[data-skin-materials]");

  if (!canvasHost) throw new Error("3D 预览容器缺失。");

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0d1d22);
  scene.fog = new THREE.Fog(0x0d1d22, 9, 18);

  const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 100);
  camera.position.set(2.8, 2.1, 3.6);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = false;
  canvasHost.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.target.set(0, 1, 0);
  controls.minDistance = 0.8;
  controls.maxDistance = 14;

  const hemi = new THREE.HemisphereLight(0xdff1e7, 0x18252a, 2.4);
  scene.add(hemi);
  const key = new THREE.DirectionalLight(0xfff0d8, 3.2);
  key.position.set(4, 7, 5);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0x8fcbb2, 1.2);
  fill.position.set(-4, 3, -3);
  scene.add(fill);

  const grid = new THREE.GridHelper(20, 40, 0x355a52, 0x203a36);
  grid.position.y = 0;
  grid.material.opacity = 0.55;
  grid.material.transparent = true;
  scene.add(grid);

  let model = null;
  let mixer = null;
  let clips = [];
  let activeAction = null;
  let raf = 0;
  let disposed = false;
  let elapsed = 0;
  let wireframe = false;
  let joints = 0;
  let materials = [];
  let dimensions = null;

  const clock = new THREE.Clock();

  function resize() {
    const rect = canvasHost.getBoundingClientRect();
    const width = Math.max(320, Math.floor(rect.width));
    const height = Math.max(280, Math.floor(rect.height));
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height, false);
  }

  function fitCamera() {
    if (!model) return;
    const box = new THREE.Box3().setFromObject(model);
    if (box.isEmpty()) return;
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    dimensions = { x: size.x, y: size.y, z: size.z };
    controls.target.copy(center);
    const maxSize = Math.max(size.x, size.y, size.z) || 1;
    const distance = maxSize / (2 * Math.tan((camera.fov * Math.PI) / 360)) * 1.65;
    camera.position.copy(center).add(new THREE.Vector3(distance * 0.75, distance * 0.55, distance));
    camera.near = Math.max(0.001, distance / 100);
    camera.far = distance * 20;
    camera.updateProjectionMatrix();
    controls.minDistance = Math.max(0.05, maxSize * 0.08);
    controls.maxDistance = Math.max(2, maxSize * 12);
    if (scene.fog) {
      scene.fog.near = distance * 0.8;
      scene.fog.far = distance * 4;
    }
    grid.scale.setScalar(Math.max(0.1, maxSize / 10));
    grid.position.y = box.min.y;
    controls.update();
  }

  function updateMeta() {
    if (metaNode) {
      metaNode.textContent = dimensions
        ? `${track.format || "3D"} · ${joints} 骨骼 · ${clips.length} 动画 · ${number(dimensions.x)} × ${number(dimensions.y)} × ${number(dimensions.z)}`
        : "";
    }
    if (materialsNode) {
      const names = materials.slice(0, 6).map((m) => m.name).filter(Boolean);
      materialsNode.textContent = names.length
        ? `材质 ${materials.length} · ${names.join(" / ")}`
        : materials.length
          ? `材质 ${materials.length}`
          : "";
    }
    if (animationSelect) {
      animationSelect.innerHTML = clips.length
        ? clips.map((clip, index) => `<option value="${index}">${clip.name || `动画 ${index + 1}`}</option>`).join("")
        : `<option value="">静态模型</option>`;
      animationSelect.disabled = !clips.length;
    }
  }

  function playClip(index) {
    if (!mixer || !clips.length) return;
    const clip = clips[index] || clips[0];
    if (!clip) return;
    if (activeAction) activeAction.stop();
    activeAction = mixer.clipAction(clip);
    activeAction.reset();
    activeAction.setLoop(THREE.LoopRepeat, Infinity);
    activeAction.play();
  }

  function onWireChange() {
    wireframe = Boolean(wireToggle?.checked);
    model?.traverse((child) => {
      if (!child.isMesh) return;
      const list = Array.isArray(child.material) ? child.material : [child.material];
      for (const material of list) {
        if (material) material.wireframe = wireframe;
      }
    });
  }

  function onScreenshot() {
    try {
      renderer.render(scene, camera);
      const link = document.createElement("a");
      link.download = `${(track.title || "模型").replace(/[\\/:*?"<>|]/g, "_")}-预览.png`;
      link.href = renderer.domElement.toDataURL("image/png");
      link.click();
    } catch (error) {
      setStatus(container, `截图失败：${error.message}`, true);
    }
  }

  function animate() {
    if (disposed) return;
    raf = requestAnimationFrame(animate);
    const delta = Math.min(clock.getDelta(), 0.1);
    elapsed += delta;
    if (mixer) mixer.update(delta);
    controls.update();
    renderer.render(scene, camera);
  }

  function onResize() {
    resize();
  }

  resize();
  window.addEventListener("resize", onResize);
  animationSelect?.addEventListener("change", () => playClip(Number(animationSelect.value) || 0));
  wireToggle?.addEventListener("change", onWireChange);
  screenshotButton?.addEventListener("click", onScreenshot);
  resetButton?.addEventListener("click", fitCamera);

  const suffix = formatOf(track);
  setStatus(container, "正在读取模型…");

  fetch(`/api/model/${encodeURIComponent(track.id)}`)
    .then((response) => {
      if (!response.ok) throw new Error(`模型读取失败（HTTP ${response.status}）`);
      return response.arrayBuffer();
    })
    .then((buffer) => {
      const onLoad = (result) => {
        if (disposed) return;
        model = result.scene || result;
        scene.add(model);
        model.traverse((child) => {
          if (child.isMesh) {
            child.castShadow = false;
            child.receiveShadow = false;
            const list = Array.isArray(child.material) ? child.material : [child.material];
            for (const material of list) {
              if (material) {
                material.side = THREE.DoubleSide;
                materials.push(material);
              }
            }
          }
          if (child.isSkinnedMesh && child.skeleton?.bones) {
            joints = Math.max(joints, child.skeleton.bones.length);
          }
        });
        clips = Array.isArray(result.animations) ? result.animations : [];
        if (clips.length) {
          mixer = new THREE.AnimationMixer(model);
          playClip(0);
          setStatus(container, `已加载 · ${clips.length} 个动画，可拖拽旋转，滚轮缩放。`);
        } else {
          setStatus(container, "模型已加载 · 没有动画片段，仅显示静态姿态。");
        }
        model.updateMatrixWorld(true);
        fitCamera();
        updateMeta();
        animate();
      };
      const onError = (error) => {
        setStatus(container, `模型解析失败：${error?.message || error}`, true);
      };
      try {
        if (suffix === "fbx") {
          const result = new FBXLoader().parse(buffer, "");
          onLoad(result);
        } else if (suffix === "glb" || suffix === "gltf") {
          const payload = suffix === "gltf" ? new TextDecoder().decode(buffer) : buffer;
          new GLTFLoader().parse(payload, "", onLoad, onError);
        } else {
          throw new Error(`暂不支持预览 .${suffix || "未知"} 格式`);
        }
      } catch (error) {
        onError(error);
      }
    })
    .catch((error) => {
      setStatus(container, error.message || "模型读取失败。", true);
    });

  const dispose = () => {
    if (disposed) return;
    disposed = true;
    cancelAnimationFrame(raf);
    window.removeEventListener("resize", onResize);
    animationSelect?.removeEventListener("change", playClip);
    wireToggle?.removeEventListener("change", onWireChange);
    screenshotButton?.removeEventListener("click", onScreenshot);
    resetButton?.removeEventListener("click", fitCamera);
    controls.dispose();
    if (mixer) mixer.stopAllAction();
    if (model) {
      scene.remove(model);
      disposeObject(model);
    }
    grid.geometry.dispose();
    grid.material.dispose();
    renderer.dispose();
    renderer.domElement.remove();
    scene.clear();
  };

  container.addEventListener(DISPOSE_EVENT, dispose, { once: true });
  return dispose;
}

export function disposeSkinPreview(container) {
  container?.dispatchEvent(new Event(DISPOSE_EVENT));
}
