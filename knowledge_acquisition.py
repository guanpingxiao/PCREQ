from utils.util import *
from utils.util import _lookup_call_module, _save_call_module_map
from extraction.getCall import get_all_used_api
from extraction.lib_module_and_package_extraction import *
from extraction.library_api_and_module import *
from call_graph.get_FDG import * 
import platform, argparse, os, json, time, requests, logging, sys
from packaging.specifiers import SpecifierSet, InvalidSpecifier
from packaging.version import parse as parse_version
import requests
import tarfile
import zipfile
import os
import tempfile
from packaging import version
from typing import Optional
import shutil
import threading
from multiprocessing import Pool, cpu_count


if (platform.system() == 'Windows'):
    slash = "\\"
else:
    slash = r"/"

library_path_prefix = ""
constraint_path_prefix = ""
version_path_prefix = ""
api_path_prefix = ""

_stats = {"downloaded": 0, "failed": 0, "skipped": 0}

def setup_path(library_path_prefix_pass, constraint_path_prefix_pass, version_path_prefix_pass, api_path_prefix_pass):
    global library_path_prefix, constraint_path_prefix, version_path_prefix, api_path_prefix
    library_path_prefix = library_path_prefix_pass
    constraint_path_prefix = constraint_path_prefix_pass
    version_path_prefix = version_path_prefix_pass
    api_path_prefix = api_path_prefix_pass
    setup_path_1(library_path_prefix, constraint_path_prefix, version_path_prefix, api_path_prefix)
def load_config(config_path):
    # config文件是一个JSON格式文件
    with open(f"./configure/{config_path}", 'r') as file:
        config = json.load(file)
    return config

def get_proj_dependency_from_requirements(file_path):
    requirements_dict = {}
    with open(file_path, 'r') as file:
        for line in file:
            # 移除行首行尾的空格和换行符
            line = line.strip()
            # 如果行不是空行并且不是注释
            if line and not line.startswith('#') and '@' not in line:
                # 按照 '==' 分割包名和版本号
                package, version = line.split('==')
                # 将包名和版本号添加到字典中
                requirements_dict[package.lower()] = version
    return requirements_dict

def get_available_version(FDG, sub_graph, python_version, target_proj_dependency, target_library, target_version):
    target_library_constraint = get_library_constraint_from_metadata(target_library, target_version, python_version)
    available_versions1 = {}
    available_versions2 = {}
    available_versions = {}
    target_library_dependency = FDG[target_library]        #得到目标库的上游项目，即目标库所依赖其他第三方库                                                  
    available_versions[target_library] = []
    available_versions[target_library].append(target_version)
    with open(f"{version_path_prefix}library_version.json", 'r') as file:
        version_ls = json.load(file)
    for proj_dependency in sub_graph:
        #print(proj_dependency)
        flag = False
        if proj_dependency not in target_proj_dependency:
            continue
        condidate_version = []
        if proj_dependency not in target_library_dependency:
            try:
                condidate_version = version_ls[proj_dependency.lower()][python_version]
            except:
                print(proj_dependency.lower())
            #print(proj_dependency)
            if len(condidate_version) >= 150:
                condidate_version = condidate_version[-150:]
            elif len(condidate_version) >= 30:
                condidate_version = condidate_version[-30:]

            #将起始requirements.txt中的约束版本放在第一个，模拟pip安装
            target_ver = target_proj_dependency[proj_dependency]
            target_ver_norm = str(parse_version(target_ver))
            match_idx = None
            for idx, v in enumerate(condidate_version):
                if str(parse_version(v)) == target_ver_norm:
                    match_idx = idx
                    break
            if match_idx is not None:
                condidate_version.pop(match_idx)
                condidate_version.append(target_ver)
                flag = True
            else:
                condidate_version.append(target_ver)
                flag = True
            pass
            #condidate_version.append(target_proj_dependency[proj_dependency])
        else:
            try:
                for version in version_ls[proj_dependency][python_version]:
                    try:                    #在目标库起始版本的约束中，但是不在目标版本的约束中
                        if is_version_compat(version, target_library_constraint[proj_dependency]):
                            condidate_version.append(version)
                    except:
                        condidate_version = version_ls[proj_dependency][python_version]
                        break
            except:
                print(proj_dependency)
            if target_proj_dependency[proj_dependency] in condidate_version:  #将起始requirements.txt中的约束版本放在第一个，模拟pip安装
                condidate_version.remove(target_proj_dependency[proj_dependency])
                condidate_version.append(target_proj_dependency[proj_dependency])
                flag = True
        if flag:
            available_versions1[proj_dependency] = condidate_version
        else:
            available_versions2[proj_dependency] = condidate_version
    sorted_available_versions1 = dict(sorted(available_versions1.items(), key=lambda item: len(item[1])))
    #print(sorted_available_versions1)
    sorted_available_versions2 = dict(sorted(available_versions2.items(), key=lambda item: len(item[1])))
    for i in sorted_available_versions1:
        available_versions[i] = sorted_available_versions1[i]
    for i in sorted_available_versions2:
        if i not in available_versions:
            available_versions[i] = sorted_available_versions2[i]
    return available_versions

def filter_versions(version_list):
    """Remove versions that fail parse_version (e.g. date-like strings like 2019.12.17)."""
    result = []
    for v in version_list:
        try:
            parse_version(v)
            result.append(v)
        except Exception:
            pass
    return result

def get_compatible_versions(package_name, python_version):
    url = f"https://pypi.org/pypi/{package_name}/json"
    try:
        response = requests.get(url).json()
    except (requests.RequestException, json.JSONDecodeError, ValueError):
        return []
    compatible_versions = []
    new_python_version = python_version.replace(".", "")
    if "releases" not in response:
        return []
    for version, files in response["releases"].items():
        for file_info in files:
            if file_info.get("python_version"):
                #print(file_info["python_version"])
                try:
                    if file_info["python_version"] == f"cp{new_python_version}":
                        compatible_versions.append(version)
                        break
                    elif file_info["python_version"] != None and f"py{python_version.split('.')[0]}" in file_info["python_version"]:
                        if "=" in file_info["requires_python"] or ">" in file_info["requires_python"] or "<" in file_info["requires_python"]:
                            if SpecifierSet(file_info["requires_python"]).contains(python_version):
                                compatible_versions.append(version)
                                break
                    elif file_info["requires_python"] == None:
                        compatible_versions.append(version)
                        break
                    elif SpecifierSet(file_info["requires_python"]).contains(python_version):
                        compatible_versions.append(version)
                        break
                except (KeyError, TypeError, InvalidSpecifier):
                    pass
    compatible_versions = filter_versions(compatible_versions)
    compatible_versions.sort(key=parse_version)
    if package_name == "torchvision" and "0.11.0" in compatible_versions:
        compatible_versions.remove("0.11.0")
    if package_name == "python-dateutil" and compatible_versions[-1] == "2.9.0":
        compatible_versions.append("2.9.0.post0")
    return compatible_versions

def _parse_wheel_tag(filename):
    """Parse a wheel filename and return (priority, is_pure).

    Priority: 1=py3-none-any, 2=cp{XX}-none-any, 3=other abi=none, <0=compiled.
    Only meaningful for .whl files; callers should handle sdist separately.
    is_pure: True if abi==none.
    """
    if not filename.endswith(".whl"):
        return -1, False  # not a wheel, caller should handle separately
    parts = filename[:-4].split("-")
    if len(parts) < 4:
        return -1, False  # malformed wheel
    # PEP 427: {dist}-{ver}-{python_tag}-{abi_tag}-{platform_tag}.whl
    platform_tag = parts[-1]
    abi_tag = parts[-2]
    python_tags = parts[2:-2]  # may have multiple (e.g. py2.py3)
    # Flatten dot-separated tags (e.g. "py2.py3" → ["py2", "py3"])
    all_tags = set()
    for t in python_tags:
        all_tags.update(t.split("."))
    is_pure = abi_tag in ("none", "abi3")
    if not is_pure:
        return -1, False  # compiled
    if platform_tag == "any":
        if any(t == "py3" or t.startswith("py3") for t in all_tags):
            return 1, True  # py3-none-any
        elif any(t.startswith("cp") for t in all_tags):
            return 2, True  # cp{XX}-none-any
    return 3, True  # abi=none but has platform tag


def _select_download_urls(package_name, version, python_version):
    """Return priority-sorted download URLs from version constraint JSON.

    Priority: pure wheel (abi=none) > compiled wheel (platform match) > sdist.
    Compiled wheels on wrong platform, .exe/.msi/.dmg/.rpm/.deb are excluded.
    """
    json_path = f"{constraint_path_prefix}{package_name}/{package_name}{version}/{package_name}.json"
    if not os.path.exists(json_path):
        return []
    try:
        with open(json_path) as f:
            data = json.load(f)
    except json.JSONDecodeError:
        logging.error("Corrupted constraint JSON, removing: %s", json_path)
        os.remove(json_path)
        return []
    except OSError:
        return []
    urls = data.get("urls", [])
    if not urls:
        return []
    # Determine current platform tag for same-tier sorting
    if sys.platform.startswith("linux"):
        plat_tag = "manylinux"
    elif sys.platform == "darwin":
        plat_tag = "macosx"
    elif sys.platform == "win32":
        plat_tag = "win"
    else:
        plat_tag = None
    scored = []
    for u in urls:
        pkg_type = u.get("packagetype")
        filename = u.get("filename", "")
        url = u.get("url", "")
        if not url:
            continue
        # Skip non-source artifacts: .exe, .msi, .dmg, .rpm, .deb
        if filename.endswith((".exe", ".msi", ".dmg", ".rpm", ".deb")):
            continue
        if pkg_type == "bdist_wheel":
            priority, is_pure = _parse_wheel_tag(filename)
            platform_ok = ("any" in filename) or (plat_tag and plat_tag in filename)
            if is_pure:
                if platform_ok:
                    pass  # keep priority 1-3
                else:
                    priority = 4  # pure wheel, wrong platform
            else:
                # Compiled wheel: has top_level.txt, better than sdist
                if platform_ok:
                    priority = 5  # compiled, matching platform
                else:
                    continue  # compiled, wrong platform → skip
        elif pkg_type == "sdist":
            priority = 6  # last resort, no top_level.txt
        else:
            continue  # unknown artifact type, skip
        scored.append((priority, url))
    scored.sort(key=lambda x: x[0])
    return [url for _, url in scored]


def _is_pure_binary_package(urls):
    """Check whether a package has NO source-capable artifacts (all compiled).

    Returns True if every artifact is a compiled wheel with no sdist or pure wheel.
    """
    if not urls:
        return False
    for u in urls:
        pkg_type = u.get("packagetype")
        filename = u.get("filename", "")
        if pkg_type == "sdist":
            return False
        priority, is_pure = _parse_wheel_tag(filename) if pkg_type == "bdist_wheel" else (4, True)
        if is_pure:
            return False
    return True

def _verify_top_level(name, extract_root):
    """Check whether a module name exists at extract_root or one level deep (e.g. src/)."""
    if os.path.isdir(os.path.join(extract_root, name)) or \
       os.path.isfile(os.path.join(extract_root, name + ".py")):
        return True
    # Search one level deeper for src/ layout
    for d in os.listdir(extract_root):
        full = os.path.join(extract_root, d)
        if os.path.isdir(full) and not d.startswith(".") and \
           not d.endswith((".dist-info", ".egg-info")):
            if os.path.isdir(os.path.join(full, name)) or \
               os.path.isfile(os.path.join(full, name + ".py")):
                return True
    return False


def _resolve_module_path(name, extract_root):
    """Find the actual path of a module within extract_root (handles src/ layout).
    Returns the subdirectory path or None if not found."""
    # Direct match
    dir_path = os.path.join(extract_root, name)
    if os.path.isdir(dir_path):
        return dir_path
    if os.path.isfile(dir_path + ".py"):
        return dir_path + ".py"
    # Search one level deep
    for d in os.listdir(extract_root):
        full = os.path.join(extract_root, d)
        if os.path.isdir(full) and not d.startswith(".") and \
           not d.endswith((".dist-info", ".egg-info")):
            dir_path = os.path.join(full, name)
            if os.path.isdir(dir_path) or os.path.isfile(dir_path + ".py"):
                return dir_path
    return None


def _select_from_top_level(entries, pkg_name, extract_dir):
    """Select best module from multi-entry top_level.txt."""
    if not entries:
        return None
    norm_pkg = pkg_name.replace("-", "_")
    matching = [e for e in entries if e.replace("-", "_") == norm_pkg]
    if len(matching) == 1:
        return matching[0]
    if matching:
        return max(matching, key=lambda e: sum(
            1 for _, _, fs in os.walk(os.path.join(extract_dir, e)) for f in fs if f.endswith(".py")))
    if entries:
        best = max(entries, key=lambda e: sum(
            1 for _, _, fs in os.walk(os.path.join(extract_dir, e)) for f in fs if f.endswith(".py"))
            if os.path.isdir(os.path.join(extract_dir, e)) else 0)
        logging.warning("top_level.txt entries %s do not match pkg %s, selected %s",
                       entries, pkg_name, best)
        return best
    return None


def _parse_setup_cfg(extract_dir):
    """Parse setup.cfg [options] to find top-level package name. Returns name or None."""
    cfg_path = os.path.join(extract_dir, "setup.cfg")
    if not os.path.isfile(cfg_path):
        return None
    try:
        from configparser import ConfigParser
        cp = ConfigParser()
        cp.read(cfg_path)
    except Exception:
        return None
    if not cp.has_section("options"):
        return None
    packages = cp.get("options", "packages", fallback="").strip()
    package_dir = cp.get("options", "package_dir", fallback="").strip()
    src_prefix = ""
    if package_dir:
        for part in package_dir.split("\n"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                k = k.strip()
                v = v.strip()
                if k == "":
                    src_prefix = v + "/"
    if not packages or packages in ("find:", "find_namespace:"):
        search_dir = os.path.join(extract_dir, src_prefix) if src_prefix else extract_dir
        if os.path.isdir(search_dir):
            for d in sorted(os.listdir(search_dir)):
                if d.startswith(".") or d.endswith((".dist-info", ".egg-info", ".data", ".libs")):
                    continue
                full = os.path.join(search_dir, d)
                if os.path.isdir(full) and os.path.isfile(os.path.join(full, "__init__.py")):
                    return d
        return None
    else:
        return packages.split()[0].strip() or None


def _score_module_candidate(dirname, pkg_name):
    """Score a directory candidate for top-level module root. Reject if < 3."""
    score = 0
    norm = pkg_name.replace("-", "_")
    is_name_match = (dirname == norm or dirname == pkg_name)
    if is_name_match:
        score += 3
    # Only penalize non-matching names (e.g. "testpath" matching "testpath" is fine)
    for prefix in ("test", "docs", "example", "bench"):
        if not is_name_match and (dirname.startswith(prefix) or
            dirname.startswith(prefix + "_") or dirname.startswith(prefix + "-")):
            score -= 5
    return score


def _write_marker(path):
    """Write an empty marker file."""
    try:
        with open(path, "w") as f:
            pass
    except OSError:
        pass


def _finish_identify(module_name, package_name, target_dir, extract_root=None):
    """Write .call_module, update cache, remove .call_module_failed.

    If extract_root is given, moves the module directory from extract_root to
    target_dir/{module_name}/ so main.py can find it at the expected path.
    """
    call_module_file = os.path.join(target_dir, ".call_module")
    call_module_failed = os.path.join(target_dir, ".call_module_failed")

    # Move module from extract_root to target_dir
    if extract_root is not None:
        module_path = _resolve_module_path(module_name, extract_root)
        if module_path is None:
            # Root-as-package: __init__.py at extract_root → root IS the module
            if os.path.isfile(os.path.join(extract_root, "__init__.py")):
                dest = os.path.join(target_dir, module_name)
                os.makedirs(dest, exist_ok=True)
                for item in os.listdir(extract_root):
                    shutil.move(os.path.join(extract_root, item),
                               os.path.join(dest, item))
            else:
                return None
        if os.path.isfile(module_path) and module_path.endswith(".py"):
            # Single-file module: move to {target_dir}/{name}.py
            dest = os.path.join(target_dir, module_name + ".py")
            if os.path.exists(dest):
                os.remove(dest)
            shutil.move(module_path, dest)
        else:
            dest = os.path.join(target_dir, module_name)
            if os.path.exists(dest):
                shutil.rmtree(dest)
            shutil.move(module_path, dest)

    with open(call_module_file, "w") as f:
        f.write(module_name)
    if os.path.exists(call_module_failed):
        os.remove(call_module_failed)
    _save_call_module_map(version_path_prefix, package_name, module_name, is_auto=True)
    return module_name


def _identify_call_module(package_name, target_dir, is_wheel=False, extract_root=None):
    """4-level identification pipeline for the top-level module of a package.

    Returns module name on success, None on failure.
    On success: writes .call_module, updates call_module_map.json.
    On failure: writes .call_module_failed.
    """
    call_module_file = os.path.join(target_dir, ".call_module")
    call_module_failed = os.path.join(target_dir, ".call_module_failed")

    # Gate: already identified
    if os.path.exists(call_module_file):
        try:
            with open(call_module_file) as f:
                return f.read().strip()
        except OSError:
            pass

    if extract_root is None or not os.path.isdir(extract_root):
        _write_marker(call_module_failed)
        return None

    # Step 1: top_level.txt (wheel only)
    if is_wheel:
        for d in os.listdir(extract_root):
            if d.endswith(".dist-info"):
                tl_path = os.path.join(extract_root, d, "top_level.txt")
                if os.path.isfile(tl_path):
                    try:
                        with open(tl_path) as f:
                            entries = [l.strip() for l in f if l.strip()]
                    except OSError:
                        entries = []
                    if entries:
                        selected = _select_from_top_level(entries, package_name, extract_root)
                        if selected and _verify_top_level(selected, extract_root):
                            return _finish_identify(selected, package_name, target_dir, extract_root)
                    break

    # Step 2: call_module_map.json
    module_from_map = _lookup_call_module(package_name)
    if module_from_map != package_name:
        if _verify_top_level(module_from_map, extract_root):
            return _finish_identify(module_from_map, package_name, target_dir, extract_root)

    # Step 3: setup.cfg
    module_from_cfg = _parse_setup_cfg(extract_root)
    if module_from_cfg and _verify_top_level(module_from_cfg, extract_root):
        return _finish_identify(module_from_cfg, package_name, target_dir, extract_root)

    # Step 4: heuristic scoring (root + one level deep for src/ layout)
    scored = []
    def _scan_candidates(search_dir, parent_dir_name=""):
        for d in os.listdir(search_dir):
            if d.startswith(".") or d.endswith((".dist-info", ".egg-info", ".data", ".libs")):
                continue
            full = os.path.join(search_dir, d)
            if not os.path.isdir(full):
                continue
            s = _score_module_candidate(d, package_name)
            if os.path.isfile(os.path.join(full, "__init__.py")):
                s += 2
            if parent_dir_name == "src":
                s += 1
            if s > 0:
                scored.append((s, d))
    _scan_candidates(extract_root)
    # Also scan known layout subdirectories: src/, lib/, py_src/
    for sub in ("src", "lib", "py_src"):
        sub_dir = os.path.join(extract_root, sub)
        if os.path.isdir(sub_dir):
            _scan_candidates(sub_dir, parent_dir_name=sub)
    if scored:
        scored.sort(reverse=True)
        best_score, best_dir = scored[0]
        # If only one candidate has __init__.py, accept with lower threshold
        threshold = 2 if len([s for s, d in scored if s >= 2]) == 1 else 3
        if best_score >= threshold:
            return _finish_identify(best_dir, package_name, target_dir, extract_root)

    # Step 4b: single-file module fallback (e.g. six.py, src/decorator.py)
    norm = package_name.replace("-", "_")
    all_py_candidates = []
    for search_dir in [extract_root] + [
        os.path.join(extract_root, sub) for sub in ("src", "lib", "py_src")
        if os.path.isdir(os.path.join(extract_root, sub))
    ]:
        for d in os.listdir(search_dir):
            if d.startswith("."):
                continue
            full = os.path.join(search_dir, d)
            if os.path.isfile(full) and d.endswith(".py"):
                mod_name = d[:-3]
                if mod_name in ("setup", "conftest", "test", "conf"):
                    continue
                if "_test" in mod_name or mod_name.endswith("_test") or \
                   "unittest" in mod_name or mod_name == "test":
                    continue
                # Name match → immediate accept
                if mod_name == norm or mod_name == package_name:
                    return _finish_identify(mod_name, package_name, target_dir, extract_root)
                all_py_candidates.append(mod_name)
    # No name match but only one candidate → accept (e.g. pysocks→socks.py)
    if len(all_py_candidates) == 1:
        return _finish_identify(all_py_candidates[0], package_name, target_dir, extract_root)

    # Step 4c: root-as-package (__init__.py at extract root)
    if os.path.isfile(os.path.join(extract_root, "__init__.py")):
        return _finish_identify(package_name, package_name, target_dir, extract_root)

    # All failed
    _write_marker(call_module_failed)
    return None


def _extract_archive(archive_path, target_dir):
    """Extract archive and move contents to target_dir, flattening sdist wrapper."""
    extract_tmp = os.path.join(os.path.dirname(archive_path), "e")
    os.makedirs(extract_tmp)
    if archive_path.endswith(('.tar.gz', '.tgz', '.tar.bz2')):
        with tarfile.open(archive_path) as tf:
            tf.extractall(extract_tmp)
    else:
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(extract_tmp)
    # Fix zero-permission entries (e.g., old colorama 0.1.x tar has mode 0o0)
    for root, dirs, files in os.walk(extract_tmp):
        for d in dirs:
            try:
                os.chmod(os.path.join(root, d), 0o755)
            except OSError:
                pass
        for f in files:
            try:
                os.chmod(os.path.join(root, f), 0o644)
            except OSError:
                pass
    items = os.listdir(extract_tmp)
    os.makedirs(target_dir, exist_ok=True)
    if len(items) == 1 and os.path.isdir(os.path.join(extract_tmp, items[0])):
        src_dir = os.path.join(extract_tmp, items[0])
        for item in os.listdir(src_dir):
            shutil.move(os.path.join(src_dir, item), os.path.join(target_dir, item))
    else:
        for item in items:
            shutil.move(os.path.join(extract_tmp, item), os.path.join(target_dir, item))

def _write_library_version(pkg, python_version, compatible_versions):
    """Atomically update library_version.json with compatible_versions for pkg."""
    lv_path = f"{version_path_prefix}library_version.json"
    if os.path.exists(lv_path):
        with open(lv_path, "r") as f:
            data = json.load(f)
    else:
        data = {}
    if pkg not in data:
        data[pkg] = {}
    data[pkg][python_version] = compatible_versions
    tmp_path = lv_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f)
    os.replace(tmp_path, lv_path)


def download_pypi_source(package_name, version = None, python_version = "3.7", output_dir = "."):
    target_dir = f"{library_path_prefix}{package_name}/{package_name}{version}"

    # Gate 1: already identified
    call_module_file = os.path.join(target_dir, ".call_module")
    if os.path.exists(call_module_file):
        try:
            with open(call_module_file) as f:
                cached = f.read().strip()
            dest = os.path.join(target_dir, cached)
            if os.path.exists(dest) or os.path.exists(dest + ".py"):
                _stats["skipped"] += 1
                return
        except OSError:
            pass

    # Gate 2: permanently broken (no source)
    if os.path.exists(target_dir + ".no_source"):
        _stats["skipped"] += 1
        return

    # Determine artifact type and download URL
    os.makedirs(target_dir, exist_ok=True)
    urls = _select_download_urls(package_name, version, python_version)

    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_path = None
        is_wheel = False

        # --- Download phase ---
        if urls:
            # Check if archive already saved
            for u in urls:
                fname = os.path.basename(u.split("#")[0].split("?")[0])
                existing = os.path.join(target_dir, fname)
                if os.path.exists(existing):
                    artifact_path = existing
                    is_wheel = fname.endswith(".whl")
                    _stats["skipped"] += 1
                    break
            if artifact_path is None:
                for url in urls:
                    fname = os.path.basename(url.split("#")[0].split("?")[0])
                    dl_path = os.path.join(tmpdir, fname)
                    success = False
                    for attempt in range(3):
                        try:
                            r = requests.get(url, timeout=7200, stream=True)
                            if r.status_code == 200:
                                expected_size = int(r.headers.get('Content-Length', 0))
                                actual_size = 0
                                with open(dl_path, "wb") as f:
                                    for chunk in r.iter_content(chunk_size=8192):
                                        f.write(chunk)
                                        actual_size += len(chunk)
                                if expected_size > 0 and actual_size != expected_size:
                                    logging.warning("Content-Length mismatch for %s: expected %d, got %d",
                                                    url[:80], expected_size, actual_size)
                                # Save archive to target_dir
                                saved = os.path.join(target_dir, fname)
                                shutil.copy2(dl_path, saved)
                                artifact_path = saved
                                is_wheel = fname.endswith(".whl")
                                success = True
                                break
                        except requests.ConnectionError as e:
                            if attempt < 2:
                                time.sleep(2 ** attempt)
                                continue
                            logging.warning("Download retry exhausted: %s", e)
                        except OSError as e:
                            logging.warning("Disk write error, skipping %s==%s: %s",
                                          package_name, version, e)
                            break
                    if success:
                        break
        else:
            # Fallback: query PyPI API directly
            pypi_url = f"https://pypi.org/pypi/{package_name}/{version}/json"
            try:
                r = requests.get(pypi_url, timeout=7200)
                if r.status_code == 200:
                    data = r.json()
                    # Platform tag for compiled wheel fallback
                    if sys.platform.startswith("linux"):
                        _plat = "manylinux"
                    elif sys.platform == "darwin":
                        _plat = "macosx"
                    elif sys.platform == "win32":
                        _plat = "win"
                    else:
                        _plat = None
                    # Priority: pure wheel > compiled wheel (platform match) > sdist
                    candidates = []
                    for u in data.get("urls", []):
                        fname = u.get("filename", "")
                        url = u.get("url", "")
                        if not url or fname.endswith((".exe", ".msi", ".dmg", ".rpm", ".deb")):
                            continue
                        pkg_type = u.get("packagetype", "")
                        if pkg_type == "bdist_wheel":
                            prio, pure = _parse_wheel_tag(fname)
                            platform_ok = ("any" in fname) or (_plat and _plat in fname)
                            if pure:
                                candidates.append((prio if platform_ok else 4, url))
                            elif platform_ok:
                                candidates.append((5, url))  # compiled, matching platform
                        elif pkg_type == "sdist":
                            candidates.append((6, url))
                    candidates.sort(key=lambda x: x[0])
                    url = candidates[0][1] if candidates else None
                    if url:
                        fname = os.path.basename(url.split("#")[0].split("?")[0])
                        dl_path = os.path.join(tmpdir, fname)
                        r2 = requests.get(url, timeout=7200, stream=True)
                        if r2.status_code == 200:
                            expected_size = int(r2.headers.get('Content-Length', 0))
                            actual_size = 0
                            with open(dl_path, "wb") as f:
                                for chunk in r2.iter_content(chunk_size=8192):
                                    f.write(chunk)
                                    actual_size += len(chunk)
                            if expected_size > 0 and actual_size != expected_size:
                                logging.warning("Content-Length mismatch for %s: expected %d, got %d",
                                                url[:80], expected_size, actual_size)
                            saved = os.path.join(target_dir, fname)
                            shutil.copy2(dl_path, saved)
                            artifact_path = saved
                            is_wheel = False
            except requests.RequestException:
                pass

        if artifact_path is None:
            _stats["failed"] += 1
            logging.warning("Download failed for %s==%s", package_name, version)
            return

        # --- Identification phase ---
        extract_dir = os.path.join(tmpdir, "extract")
        # Copy archive to tmpdir so _extract_archive's temp dir stays in tmpdir
        tmp_archive = os.path.join(tmpdir, os.path.basename(artifact_path))
        shutil.copy2(artifact_path, tmp_archive)
        _extract_archive(tmp_archive, extract_dir)
        if not any(f.endswith('.py') for _, _, files in os.walk(extract_dir)
                   for f in files):
            with open(target_dir + ".no_source", "w") as _:
                pass
            if os.path.exists(target_dir):
                shutil.rmtree(target_dir)
            _stats["failed"] += 1
            logging.warning("No source files in %s==%s, skipping",
                          package_name, version)
            return

        identified = _identify_call_module(package_name, target_dir,
                                           is_wheel=is_wheel,
                                           extract_root=extract_dir)
        if identified is not None:
            _stats["downloaded"] += 1
        else:
            _stats["failed"] += 1
            logging.warning("call_module identification failed for %s==%s",
                          package_name, version)

def extract_fine_grained_knowledge(lib, version):
    # Prefer .call_module (set by identification) over get_library_call_module
    call_module_file = f"{library_path_prefix}{lib}/{lib}{version}/.call_module"
    if os.path.exists(call_module_file):
        with open(call_module_file) as f:
            library_call_module = f.read().strip()
    else:
        library_call_module = get_library_call_module(lib)
    library_path = f"{library_path_prefix}{lib}/{lib}{version}/{library_call_module}"
    if os.path.isfile(library_path + ".py"):
        # Single-file module (e.g. six.py)
        from extraction.library_api_and_module import extract_info_from_py_file
        root_dir = f"{library_path_prefix}{lib}/{lib}{version}"
        res = extract_info_from_py_file(library_path + ".py", root_dir)
        # Strip version-dir prefix from keys (extract_info_from_py_file prepends
        # root_dir's basename, e.g. "six1.16.0.six.func" → "six.func")
        version_dir = os.path.basename(root_dir.rstrip("/"))
        version_prefix = version_dir + "."
        for key_type in ("functions", "classes", "methods"):
            new_dict = {}
            for k, v in res[key_type].items():
                new_k = k[len(version_prefix):] if k.startswith(version_prefix) else k
                new_dict[new_k] = v
            res[key_type] = new_dict
        res["global_vars"] = [
            v[len(version_prefix):] if v.startswith(version_prefix) else v
            for v in res.get("global_vars", [])
        ]
        res["modules"] = [library_call_module]
        res["api_usage"] = []
    else:
        res = extract_from_directory(library_path)
        print("********************")
        dir = get_python_modules_and_packages_from_dir(library_path, library_call_module)
        init_dir = get_python_modules_and_packages_from_init(library_path, library_call_module)
        dir.update(init_dir)
        res["modules"] = list(dir)
        try:
            api_usage_in_target_library, _1, __2, _3  = get_all_used_api(library_path, library_call_module)
        except (SyntaxError, ValueError, OSError):
            api_usage_in_target_library = []
        res["api_usage"] = list(api_usage_in_target_library)
    funcs = res["functions"]
    new_funcs = shortenPath(funcs, lib, version, library_path_prefix)
    res["functions"] = new_funcs
    classes = res["classes"]
    new_classes = shortenPath(classes, lib, version, library_path_prefix)
    res["classes"] = new_classes
    api_path = f"{api_path_prefix}{lib}/{version}.json"
    # Quality guard: empty modules → extraction failed
    if len(res.get("modules", [])) == 0:
        fail_path = api_path + ".failed"
        logging.warning("Empty modules for %s==%s, marking as .failed", lib, version)
        try:
            open(fail_path, "w").close()
        except OSError:
            pass
        return
    tmp_path = api_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(res, f)
    os.replace(tmp_path, api_path)
    # Clear stale .failed marker
    fail_path = api_path + ".failed"
    if os.path.exists(fail_path):
        os.remove(fail_path)

def task(args):
    lib, version = args
    #print(f"Extracting Knowledge-{lib}-{version}")
    extract_fine_grained_knowledge(lib, version)

    

if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
    start = time.time()

    # 创建ArgumentParser对象
    parser = argparse.ArgumentParser(description="命令行工具示例")
    # 添加--config参数，指定config文件路径
    parser.add_argument('--config', type=str, required=True, help="配置文件路径")
    # 解析命令行参数
    args = parser.parse_args()
    # 获取config文件路径
    config_path = args.config

    # 加载并处理config文件
    config = load_config(config_path)
    
    proj_path = config["projPath"]
    target_project = proj_path.split("/")[-1]
    target_library = config["targetLibrary"]
    start_version = config["startVersion"]
    target_version = config["targetVersion"]
    python_version = config["pythonVersion"]
    start_requirements_path = config["requirementsPath"]
    knowledge_path = config["knowledgePath"].rstrip("/") + "/"
    library_path_prefix = f"{knowledge_path}libraries/"
    constraint_path_prefix = f"{knowledge_path}version_constraint/"
    version_path_prefix = f"{knowledge_path}"
    api_path_prefix = f"{knowledge_path}library_api/"
    setup_path(library_path_prefix, constraint_path_prefix, version_path_prefix, api_path_prefix)

    # auto-create knowledge directories
    for p in [knowledge_path, library_path_prefix, constraint_path_prefix, api_path_prefix]:
        os.makedirs(p, exist_ok=True)

    # add file logging (append across runs, INFO+ to file, WARNING+ to console)
    log_file = os.path.join(knowledge_path, "knowledge_acquisition.log")
    fh = logging.FileHandler(log_file, mode='a')
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logging.getLogger().addHandler(fh)
    logging.getLogger().setLevel(logging.INFO)
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
            h.setLevel(logging.WARNING)
    logging.info("=== Build: %s | %s %s->%s | py%s ===",
                 target_project, target_library, start_version, target_version, python_version)

    fake_start_proj_dependency = get_proj_dependency_from_requirements(start_requirements_path)
    start_proj_dependency = {}
    for i in fake_start_proj_dependency:
        if fake_start_proj_dependency[i] == "0.0.0" or fake_start_proj_dependency[i] == "0.0" or fake_start_proj_dependency[i] == "0":
            pass
        else:
            start_proj_dependency[i] = fake_start_proj_dependency[i]
    
    target_proj_dependency = start_proj_dependency.copy()
    target_proj_dependency[target_library] = target_version
    FDG = get_FDG_from_requirements(target_proj_dependency, python_version)
    sub_graph = get_sub_graph(FDG, target_library)
    #获取所有的候选版本（含sub_graph可达依赖和直接声明依赖）
    all_packages = set(sub_graph) | set(target_proj_dependency.keys())
    if os.path.exists(f"{version_path_prefix}library_version.json"):
        with open(f"{version_path_prefix}library_version.json", "r") as f:
            _cached_versions = json.load(f)
    else:
        _cached_versions = {}
    for i in all_packages:
        library_call_module = get_library_call_module(i)
        if i in _cached_versions and python_version in _cached_versions[i]:
            compatible_versions = _cached_versions[i][python_version]
            # Skip download loop if API extraction already succeeded,
            # but still refresh the version list from PyPI in case new
            # versions appeared (e.g. pre-releases were previously filtered).
            api_dir = f"{api_path_prefix}{i}/"
            if os.path.isdir(api_dir) and any(f.endswith('.json') for f in os.listdir(api_dir)):
                fresh = get_compatible_versions(i, python_version)
                if len(fresh) > len(compatible_versions):
                    compatible_versions = fresh
                    # Download only newly appearing versions
                    old_set = set(_cached_versions[i][python_version])
                    for j in fresh:
                        if j in old_set:
                            continue
                        if not os.path.exists(f"{constraint_path_prefix}{i}/{i}{j}/{i}.json"):
                            download_from_data(i, j)
                        print(f"Downloading {i}{j}")
                        download_pypi_source(i, j, python_version)
                if len(fresh) != len(_cached_versions[i][python_version]):
                    _write_library_version(i, python_version, compatible_versions)
                continue
        else:
            compatible_versions = get_compatible_versions(i, python_version)
        #print(compatible_versions)
        for j in compatible_versions:
            if not os.path.exists(f"{constraint_path_prefix}{i}/{i}{j}/{i}.json"):
                download_from_data(i, j)
            print(f"Downloading {i}{j}")
            download_pypi_source(i, j, python_version)
        _write_library_version(i, python_version, compatible_versions)

    # Discover transitive dependencies from all versions of all known libraries
    # (cached per library_version.json state — only rescanned when lib list changes)
    with open(f"{version_path_prefix}library_version.json", 'r') as file:
        version_ls = json.load(file)
    known_libs = set(all_packages)
    discovery_cache = f"{version_path_prefix}discovery_cache.json"
    lib_names_key = sorted(version_ls.keys())
    discovered = set()
    cache_hit = False
    if os.path.exists(discovery_cache):
        try:
            with open(discovery_cache, 'r') as f:
                cache = json.load(f)
            if (cache.get('lib_names') == lib_names_key and
                    cache.get('python_version') == python_version):
                discovered = set(cache.get('discovered', []))
                cache_hit = True
        except (json.JSONDecodeError, KeyError):
            pass
    if not cache_hit:
        for lib in list(all_packages):
            for ver in version_ls.get(lib, {}).get(python_version, []):
                constraint = get_library_constraint_from_metadata(lib, ver, python_version)
                for dep in constraint:
                    base_dep = dep.split('[')[0]
                    if base_dep not in known_libs and base_dep not in discovered:
                        discovered.add(base_dep)
        cache = {'lib_names': lib_names_key, 'python_version': python_version,
                 'discovered': list(discovered)}
        tmp_cache = discovery_cache + ".tmp"
        with open(tmp_cache, "w") as f:
            json.dump(cache, f)
        os.replace(tmp_cache, discovery_cache)
    # Download and register newly discovered libraries
    for dep in discovered:
        print(f"Discovered transitive dependency: {dep}")
        compatible_versions = get_compatible_versions(dep, python_version)
        # Check if this is a source-only or binary-only package
        pypi_url = f'https://pypi.org/pypi/{dep}/json'
        has_sdist = False
        try:
            r = requests.get(pypi_url, timeout=7200)
            if r.status_code == 200:
                urls = r.json().get('urls', [])
                has_sdist = any(u.get('packagetype') == 'sdist' for u in urls)
        except requests.RequestException:
            pass
        if has_sdist:
            for ver in compatible_versions:
                if not os.path.exists(f"{constraint_path_prefix}{dep}/{dep}{ver}/{dep}.json"):
                    download_from_data(dep, ver)
                download_pypi_source(dep, ver, python_version)
            with open(f"{version_path_prefix}library_version.json", "r") as f:
                data = json.load(f)
            data[dep] = {python_version: compatible_versions}
            lv_path = f"{version_path_prefix}library_version.json"
            tmp_path = lv_path + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(data, f)
            os.replace(tmp_path, lv_path)
            all_packages.add(dep)
        else:
            print(f"  Skipping {dep} (binary-only, no source distribution)")

    available_version = get_available_version(FDG, sub_graph, python_version, target_proj_dependency, target_library, target_version)
    available_version[target_library].append(start_version)
    #补全target_proj_dependency中未被sub_graph覆盖的孤立包
    with open(f"{version_path_prefix}library_version.json", 'r') as file:
        version_ls = json.load(file)
    for pkg in target_proj_dependency:
        if pkg not in available_version:
            try:
                available_version[pkg] = version_ls[pkg][python_version]
            except KeyError:
                pass
    #补全新发现的传递依赖
    for dep in discovered:
        if dep not in available_version:
            try:
                available_version[dep] = version_ls[dep][python_version]
            except KeyError:
                pass
    #print(available_version)

    all_library = list(target_proj_dependency.keys()) + [d for d in discovered if d in all_packages]
    #print(all_library)
    for lib in all_library:
        if not os.path.exists(f"{api_path_prefix}{lib}/"):
            os.makedirs(f"{api_path_prefix}{lib}/")
    tasks = []
    for lib in all_library:
        for version in available_version[lib]:
            if not os.path.exists(f"{api_path_prefix}{lib}/{version}.json"):
                print(f"Extracting Knowledge-{lib}-{version}")
                tasks.append((lib, version))
    #print(tasks)
    sys.setrecursionlimit(5000)
    cleanup_temp_files()
    with Pool(processes=min(20, cpu_count())) as pool:
        pool.map(task, tasks)

    print("Build complete: %d downloaded, %d failed, %d skipped"
          % (_stats["downloaded"], _stats["failed"], _stats["skipped"]))
    logging.info("Build complete: %d downloaded, %d failed, %d skipped",
                 _stats["downloaded"], _stats["failed"], _stats["skipped"])


        
            


    
    