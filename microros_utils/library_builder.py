import os, sys
import yaml
import shutil

from .utils import run_cmd
from .repositories import Repository, Sources

class CMakeToolchain:
    def __init__(self, path, cc, cxx, ar, cflags, cxxflags):
        cmake_toolchain = """include(CMakeForceCompiler)
set(CMAKE_SYSTEM_NAME Generic)

set(CMAKE_CROSSCOMPILING 1)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

SET (CMAKE_C_COMPILER_WORKS 1)
SET (CMAKE_CXX_COMPILER_WORKS 1)

set(CMAKE_C_COMPILER {C_COMPILER})
set(CMAKE_CXX_COMPILER {CXX_COMPILER})
set(CMAKE_AR {AR_COMPILER})

set(CMAKE_C_FLAGS_INIT "{C_FLAGS}" CACHE STRING "" FORCE)
set(CMAKE_CXX_FLAGS_INIT "{CXX_FLAGS}" CACHE STRING "" FORCE)

set(__BIG_ENDIAN__ 0)"""

        cmake_toolchain = cmake_toolchain.format(C_COMPILER=cc, CXX_COMPILER=cxx, AR_COMPILER=ar, C_FLAGS=cflags, CXX_FLAGS=cxxflags)

        with open(path, "w") as file:
            file.write(cmake_toolchain)

        self.path = os.path.realpath(file.name)

class Build:
    def __init__(self, library_folder, packages_folder, distro, python_env):
        self.library_folder = library_folder
        self.packages_folder = packages_folder
        # Default build folder inside the project
        default_build = os.path.join(library_folder, "build")

        # On Windows, very long paths (OneDrive + deep nests) can break tools
        # like ninja and CMake. Use a short temp-based build folder when the
        # default path is long to avoid "Filename longer than 260 characters".
        if sys.platform == 'win32' and len(os.path.abspath(default_build)) > 200:
            temp_base = os.environ.get('TEMP') or os.environ.get('TMP') or 'C:\\tmp'
            # create a short, per-project unique folder name
            short_name = 'microros_build_' + hex(abs(hash(os.path.abspath(library_folder))))[2:10]
            self.build_folder = os.path.join(temp_base, short_name)
            print(f"Note: using short build folder '{self.build_folder}' to avoid long path issues on Windows")
        else:
            self.build_folder = default_build
        self.distro = distro

        self.dev_packages = []
        self.mcu_packages = []

        self.dev_folder = self.build_folder + '/dev'
        self.dev_src_folder = self.dev_folder + '/src'
        self.mcu_folder = self.build_folder + '/mcu'
        self.mcu_src_folder = self.mcu_folder + '/src'

        self.library_path = library_folder + '/libmicroros'
        self.library = self.library_path + "/libmicroros.a"
        self.includes = self.library_path+ '/include'
        self.library_name = "microros"
        self.python_env = python_env
        self.env = {}

    def run(self, meta, toolchain, user_meta = ""):
        if os.path.exists(self.library):
            print("micro-ROS already built")
            return

        self.check_env()
        self.download_dev_environment()
        self.build_dev_environment()
        self.download_mcu_environment()
        self.build_mcu_environment(meta, toolchain, user_meta)
        self.package_mcu_library()

    def ignore_package(self, name):
        for p in self.mcu_packages:
            if p.name == name:
                p.ignore()

    def check_env(self):
        ROS_DISTRO = os.getenv('ROS_DISTRO')

        if (ROS_DISTRO):
            PATH = os.getenv('PATH')
            os.environ['PATH'] = PATH.replace('/opt/ros/{}/bin:'.format(ROS_DISTRO), '')
            os.environ.pop('AMENT_PREFIX_PATH', None)

        RMW_IMPLEMENTATION = os.getenv('RMW_IMPLEMENTATION')

        if (RMW_IMPLEMENTATION):
            os.environ['RMW_IMPLEMENTATION'] = "rmw_microxrcedds"

        # Copy environment and make Python bytecode write safe for long/onedrive paths
        self.env = os.environ.copy()

        # Avoid writing .pyc files into deep OneDrive/project paths which may fail
        # Use PYTHONDONTWRITEBYTECODE to disable .pyc writes, and also set
        # PYTHONPYCACHEPREFIX to a short build-local folder so tools that still
        # expect a cache directory will use it.
        try:
            pycache_dir = os.path.abspath(os.path.join(self.build_folder, 'pycache'))
            os.makedirs(pycache_dir, exist_ok=True)
            # Prefer redirecting pycache, but also set don't write bytecode as a fallback
            self.env['PYTHONPYCACHEPREFIX'] = pycache_dir
            self.env['PYTHONDONTWRITEBYTECODE'] = '1'
        except Exception:
            # If anything fails here, we still continue with the copied env
            pass

    def download_dev_environment(self):
        os.makedirs(self.dev_src_folder, exist_ok=True)
        print("Downloading micro-ROS dev dependencies")
        for repo in Sources.dev_environments[self.distro]:
            repo.clone(self.dev_src_folder)
            print("\t - Downloaded {}".format(repo.name))
            self.dev_packages.extend(repo.get_packages())

    def build_dev_environment(self):
        print("Building micro-ROS dev dependencies")
        
        # Fix build: Ignore rmw_test_fixture_implementation in rolling
        touch_command = ''
        if self.distro in ('rolling', 'kilted'):
            touch_command = 'touch src/ament_cmake_ros/rmw_test_fixture_implementation/COLCON_IGNORE && '
        
        # Determine the correct activation script and syntax for the platform
        if sys.platform == 'win32':
            # Windows: use Scripts/activate.bat
            activate_script = self.python_env.replace('/bin/activate', '/Scripts/activate.bat')
            source_cmd = f'call "{activate_script}"'
            generator_flag = '-G Ninja'
        else:
            # Unix/Linux/macOS: use bin/activate with dot-source
            source_cmd = f'. {self.python_env}'
            generator_flag = ''

        # Use the running Python executable instead of shell `which` backticks
        python_exec = sys.executable

        cmake_args = f"{generator_flag} -DBUILD_TESTING=OFF -DPython3_EXECUTABLE=\"{python_exec}\""
        command = f'cd "{self.dev_folder}" && {touch_command}{source_cmd} && colcon build --cmake-args {cmake_args}'
        result = run_cmd(command, env=self.env)

        if 0 != result.returncode:
            print("Build dev micro-ROS environment failed: \n {}".format(result.stderr.decode("utf-8")))
            sys.exit(1)

    def download_mcu_environment(self):
        os.makedirs(self.mcu_src_folder, exist_ok=True)
        print("Downloading micro-ROS library")
        for repo in Sources.mcu_environments[self.distro]:
            repo.clone(self.mcu_src_folder)
            self.mcu_packages.extend(repo.get_packages())
            for package in repo.get_packages():
                if package.name in Sources.ignore_packages[self.distro] or package.name.endswith("_cpp"):
                    package.ignore()

                print('\t - Downloaded {}{}'.format(package.name, " (ignored)" if package.ignored else ""))

        self.download_extra_packages()

    def download_extra_packages(self):
        if not os.path.exists(self.packages_folder):
            print("\t - Extra packages folder not found, skipping...")
            return

        print("Checking extra packages")

        # Load and clone repositories from extra_packages.repos file
        extra_repos = self.get_repositories_from_yaml("{}/extra_packages.repos".format(self.packages_folder))
        for repo_name in extra_repos:
            repo_values = extra_repos[repo_name]
            version = repo_values['version'] if 'version' in repo_values else None
            Repository(repo_name, repo_values['url'], self.distro, version).clone(self.mcu_src_folder)
            print("\t - Downloaded {}".format(repo_name))

        extra_folders = os.listdir(self.packages_folder)
        if 'extra_packages.repos' in extra_folders:
            extra_folders.remove('extra_packages.repos')

        for folder in extra_folders:
            print("\t - Adding {}".format(folder))

        shutil.copytree(self.packages_folder, self.mcu_src_folder, ignore=shutil.ignore_patterns('extra_packages.repos'), dirs_exist_ok=True)

    def get_repositories_from_yaml(self, yaml_file):
        repos = {}
        try:
            with open(yaml_file, 'r') as repos_file:
                root = yaml.safe_load(repos_file)
                repositories = root['repositories']

            if repositories:
                for path in repositories:
                    repo = {}
                    attributes = repositories[path]
                    try:
                        repo['type'] = attributes['type']
                        repo['url'] = attributes['url']
                        if 'version' in attributes:
                            repo['version'] = attributes['version']
                    except KeyError as e:
                        continue
                    repos[path] = repo
        except (yaml.YAMLError, KeyError, TypeError) as e:
            print("Error on {}: {}".format(yaml_file, e))
        finally:
            return repos

    def build_mcu_environment(self, meta_file, toolchain_file, user_meta = ""):
        print("Building micro-ROS library")

        common_meta_path = self.library_folder + '/metas/common.meta'
        
        # Determine the correct activation script and syntax for the platform
        if sys.platform == 'win32':
            # Windows: use Scripts/activate.bat and setup.bat
            activate_script = self.python_env.replace('/bin/activate', '/Scripts/activate.bat')
            setup_script = f"{self.dev_folder}/install/setup.bat"
            source_cmd = f'call "{activate_script}"'
            dev_source_cmd = f'call "{setup_script}"'
            generator_flag = '-G Ninja'
        else:
            # Unix/Linux/macOS: use bin/activate and setup.sh with dot-source
            dev_source_cmd = f'. {self.dev_folder}/install/setup.sh'
            source_cmd = f'. {self.python_env}'
            generator_flag = ''

        # Use the running Python executable instead of shell `which` backticks
        python_exec = sys.executable

        cmake_args = f"{generator_flag} -DCMAKE_POSITION_INDEPENDENT_CODE:BOOL=OFF  -DTHIRDPARTY=ON  -DBUILD_SHARED_LIBS=OFF  -DBUILD_TESTING=OFF  -DCMAKE_BUILD_TYPE=Release -DCMAKE_TOOLCHAIN_FILE={toolchain_file} -DPython3_EXECUTABLE=\"{python_exec}\""
        colcon_command = f"{source_cmd} && colcon build --merge-install --packages-ignore-regex=.*_cpp --metas {common_meta_path} {meta_file} {user_meta} --cmake-args {cmake_args}"
        command = f'cd "{self.mcu_folder}" && {dev_source_cmd} && {colcon_command}'
        result = run_cmd(command, env=self.env)

        if 0 != result.returncode:
            print("Build mcu micro-ROS environment failed: \n{}".format(result.stderr.decode("utf-8")))
            sys.exit(1)

    def package_mcu_library(self):
        binutils_path = self.resolve_binutils_path()
        aux_folder = self.build_folder + "/aux"

        shutil.rmtree(aux_folder, ignore_errors=True)
        shutil.rmtree(self.library_path, ignore_errors=True)
        os.makedirs(aux_folder, exist_ok=True)
        os.makedirs(self.library_path, exist_ok=True)
        for root, dirs, files in os.walk(self.mcu_folder + "/install/lib"):
            for f in files:
                if f.endswith('.a'):
                    os.makedirs(aux_folder + "/naming", exist_ok=True)
                    os.chdir(aux_folder + "/naming")
                    os.system("{}ar x {}".format(binutils_path, root + "/" + f))
                    for obj in [x for x in os.listdir() if x.endswith('obj')]:
                        os.rename(obj, '../' + f.split('.')[0] + "__" + obj)

        os.chdir(aux_folder)
        command = "{binutils}ar rc libmicroros.a $(ls *.o *.obj 2> /dev/null); rm *.o *.obj 2> /dev/null; {binutils}ranlib libmicroros.a".format(binutils=binutils_path)
        result = run_cmd(command)

        if 0 != result.returncode:
            print("micro-ROS static library build failed: \n{}".format(result.stderr.decode("utf-8")))
            sys.exit(1)

        os.rename('libmicroros.a', self.library)

        # Copy includes
        shutil.copytree(self.build_folder + "/mcu/install/include", self.includes)

        # Fix include paths
        include_folders = os.listdir(self.includes)

        for folder in include_folders:
            folder_path = self.includes + "/{}".format(folder)
            repeated_path = folder_path + "/{}".format(folder)

            if os.path.exists(repeated_path):
                shutil.copytree(repeated_path, folder_path, copy_function=shutil.move, dirs_exist_ok=True)
                shutil.rmtree(repeated_path)

    def resolve_binutils_path(self):
        if sys.platform == "darwin":
            homebrew_binutils_path = "/opt/homebrew/opt/binutils/bin/"
            if os.path.exists(homebrew_binutils_path):
                return homebrew_binutils_path

            print("ERROR: GNU binutils not found. ({}) Please install binutils with homebrew: brew install binutils"
                  .format(homebrew_binutils_path))
            sys.exit(1)

        return ""
