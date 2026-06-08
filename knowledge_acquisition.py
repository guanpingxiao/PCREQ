from utils.util import *
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

def _select_download_urls(package_name, version, python_version):
    """Return priority-sorted download URLs from version constraint JSON.

    Priority: sdist > cpXX wheel (current platform) > other cpXX wheels > rest.
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
    # classify
    sdist = []
    curr_plat = []
    other_cp = []
    rest = []
    py_tag = f"cp{python_version.replace('.', '')}"
    if sys.platform.startswith("linux"):
        plat_tag = "manylinux"
    elif sys.platform == "darwin":
        plat_tag = "macosx"
    elif sys.platform == "win32":
        plat_tag = "win"
    else:
        plat_tag = None
    for u in urls:
        if u.get("packagetype") == "sdist":
            sdist.append(u["url"])
        elif u.get("python_version") == py_tag:
            if plat_tag and plat_tag in u.get("filename", ""):
                curr_plat.append(u["url"])
            else:
                other_cp.append(u["url"])
        else:
            rest.append(u["url"])
    return sdist + curr_plat + other_cp + rest

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
            os.chmod(os.path.join(root, d), 0o755)
        for f in files:
            os.chmod(os.path.join(root, f), 0o644)
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
    call_module = get_library_call_module(package_name)
    if os.path.exists(target_dir + ".no_source"):
        _stats["skipped"] += 1
        return
    call_path = os.path.join(target_dir, call_module)
    if os.path.exists(call_path) or os.path.exists(call_path + ".py"):
        # Verify integrity: must have at least one .py file
        try:
            if os.path.isdir(call_path) and not any(f.endswith('.py') for f in os.listdir(call_path)):
                shutil.rmtree(target_dir)
            elif os.path.isdir(call_path) or os.path.exists(call_path + ".py"):
                _stats["skipped"] += 1
                return
        except OSError:
            shutil.rmtree(target_dir)
    # remove stale empty/incomplete directory
    if os.path.exists(target_dir):
        if any(f.endswith('.py') for _, _, files in os.walk(target_dir) for f in files):
            _stats["skipped"] += 1
            return
        shutil.rmtree(target_dir)

    with tempfile.TemporaryDirectory() as tmpdir:
        urls = _select_download_urls(package_name, version, python_version)
        if urls:
            for url in urls:
                filename = os.path.basename(url.split("#")[0].split("?")[0])
                path = os.path.join(tmpdir, filename)
                for attempt in range(3):
                    try:
                        r = requests.get(url, timeout=1800, stream=True)
                        if r.status_code == 200:
                            expected_size = int(r.headers.get('Content-Length', 0))
                            actual_size = 0
                            with open(path, "wb") as f:
                                for chunk in r.iter_content(chunk_size=8192):
                                    f.write(chunk)
                                    actual_size += len(chunk)
                            if expected_size > 0 and actual_size != expected_size:
                                logging.warning("Content-Length mismatch for %s: expected %d, got %d",
                                                url[:80], expected_size, actual_size)
                                # still accept the file — CDN proxies often report wrong size
                            # Extract to tmp dir, then atomically rename
                            extract_tmp = target_dir + ".tmp"
                            if os.path.exists(extract_tmp):
                                shutil.rmtree(extract_tmp)
                            _extract_archive(path, extract_tmp)
                            if os.path.exists(target_dir):
                                shutil.rmtree(target_dir)
                            os.replace(extract_tmp, target_dir)
                            if any(f.endswith('.py') for _, _, files in os.walk(target_dir)
                                   for f in files):
                                _stats["downloaded"] += 1
                            else:
                                with open(target_dir + ".no_source", "w") as _:
                                    pass
                                _stats["failed"] += 1
                                shutil.rmtree(target_dir)
                                logging.warning("No source files in %s==%s, skipping",
                                                package_name, version)
                            break
                    except requests.ConnectionError as e:
                        if attempt < 2:
                            time.sleep(2 ** attempt)
                            continue
                        logging.warning("Download retry exhausted: %s: %s", url[:80], e)
                    except OSError as e:
                        logging.warning("Disk write error, skipping %s==%s: %s", package_name, version, e)
                        break
                else:
                    continue  # retry exhausted, try next URL
                break  # success, stop URL iteration
        else:
            # no constraint JSON available yet; download from pypi.org API directly
            pypi_url = f"https://pypi.org/pypi/{package_name}/{version}/json"
            try:
                r = requests.get(pypi_url, timeout=30)
                if r.status_code == 200:
                    data = r.json()
                    for u in data.get("urls", []):
                        if u.get("packagetype") == "sdist":
                            url = u["url"]
                            break
                    else:
                        url = data["urls"][0]["url"] if data.get("urls") else None
                    if url:
                        path = os.path.join(tmpdir, os.path.basename(url.split("#")[0].split("?")[0]))
                        r2 = requests.get(url, timeout=1800, stream=True)
                        if r2.status_code == 200:
                            expected_size = int(r2.headers.get('Content-Length', 0))
                            actual_size = 0
                            with open(path, "wb") as f:
                                for chunk in r2.iter_content(chunk_size=8192):
                                    f.write(chunk)
                                    actual_size += len(chunk)
                            if expected_size > 0 and actual_size != expected_size:
                                logging.warning("Content-Length mismatch for %s: expected %d, got %d",
                                                url[:80], expected_size, actual_size)
                            extract_tmp = target_dir + ".tmp"
                            if os.path.exists(extract_tmp):
                                shutil.rmtree(extract_tmp)
                            _extract_archive(path, extract_tmp)
                            if os.path.exists(target_dir):
                                shutil.rmtree(target_dir)
                            os.replace(extract_tmp, target_dir)
                            if any(f.endswith('.py') for _, _, files in os.walk(target_dir)
                                   for f in files):
                                _stats["downloaded"] += 1
                            else:
                                with open(target_dir + ".no_source", "w") as _:
                                    pass
                                _stats["failed"] += 1
                                shutil.rmtree(target_dir)
                                logging.warning("No source files in %s==%s, skipping",
                                                package_name, version)
            except requests.RequestException:
                pass

    # Download failed, nothing to extract
    if not os.path.exists(target_dir):
        return

    # handle src-layout: if call_module is nested (e.g., src/PIL), move to root
    if not os.path.exists(os.path.join(target_dir, call_module)):
        src_chk = os.path.join(target_dir, "src", call_module)
        if os.path.isdir(src_chk):
            shutil.move(src_chk, os.path.join(target_dir, call_module))
        else:
            for root, dirs, _ in os.walk(target_dir):
                for d in dirs:
                    if d == call_module:
                        try:
                            shutil.move(os.path.join(root, d), os.path.join(target_dir, d))
                        except shutil.Error:
                            pass  # destination already exists, call_module is in place
                        break
        # auto-detect: scan for package root when call_module not found
        if not os.path.exists(os.path.join(target_dir, call_module)):
            found = None
            for d in sorted(os.listdir(target_dir)):
                full = os.path.join(target_dir, d)
                if os.path.isdir(full) and not d.startswith('.') and \
                   not d.endswith(('.dist-info', '.libs', '.data', '.egg-info')):
                    if os.path.exists(os.path.join(full, '__init__.py')) or \
                       any(f.endswith('.py') for f in os.listdir(full)):
                        found = full
                        break
                    # Search one level deeper (e.g. src/ layout)
                    if d == 'src' and os.path.isdir(full):
                        for sd in os.listdir(full):
                            sfull = os.path.join(full, sd)
                            if os.path.isdir(sfull) and not sd.startswith('.') and \
                               (os.path.exists(os.path.join(sfull, '__init__.py')) or
                                any(f.endswith('.py') for f in os.listdir(sfull))):
                                found = sfull
                                break
                        if found:
                            break
            if found:
                shutil.move(found, os.path.join(target_dir, call_module))
        has_py = any(True for _, _, files in os.walk(target_dir)
                     for f in files if f.endswith('.py'))
        if not has_py:
            _stats["failed"] += 1
            logging.warning("Download failed for %s==%s", package_name, version)

def extract_fine_grained_knowledge(lib, version):  
    library_call_module = get_library_call_module(lib)
    library_path = f"{library_path_prefix}{lib}/{lib}{version}/{library_call_module}"
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
    tmp_path = api_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(res, f)
    os.replace(tmp_path, api_path)

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
            r = requests.get(pypi_url, timeout=30)
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


        
            


    
    