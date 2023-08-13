from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import httpx
import typer
import yaml
from dotenv import load_dotenv
from rich import print

app = typer.Typer()

HIDDEN_CONFIG_FILENAME = ".airflowctl/config.yaml"
SETTINGS_FILENAME = "settings.yaml"


def create_project(project_name: str, airflow_version: str, python_version: str):
    # Create the project directory
    project_dir = Path(project_name).absolute()
    project_dir.mkdir(exist_ok=True)

    # if directory is not empty, prompt user to confirm
    if any(project_dir.iterdir()):
        typer.confirm(
            f"Directory {project_dir} is not empty. Continue?",
            abort=True,
        )

    # Create the dags directory
    dags_dir = Path(project_dir / "dags")
    dags_dir.mkdir(exist_ok=True)

    # Copy the example dags from dags directory
    from_dir = Path(__file__).parent / "dags"
    for file in from_dir.iterdir():
        # Ignore if file exists
        if (dags_dir / file.name).exists():
            continue
        to_file = Path(dags_dir / file.name)
        to_file.write_text(file.read_text())

    # Create the plugins directory
    plugins_dir = Path(project_dir / "plugins")
    plugins_dir.mkdir(exist_ok=True)

    # Create requirements.txt
    requirements_file = Path(project_dir / "requirements.txt")
    requirements_file.touch(exist_ok=True)

    # Create .gitignore
    gitignore_file = Path(project_dir / ".gitignore")
    gitignore_file.touch(exist_ok=True)
    with open(gitignore_file, "w") as f:
        f.write(
            """
.git
airflow.cfg
airflow.db
airflow-webserver.pid
logs
.DS_Store
__pycache__/
.env
.venv
.airflowctl
""".strip()
        )

    # Initialize the settings file
    settings_file = Path(project_dir / SETTINGS_FILENAME)
    if not settings_file.exists():
        file_contents = f"""
# Airflow version to be installed
airflow_version: {airflow_version}
# Python version for the project
python_version: "{python_version}"

# Airflow conn
connections: {{}}
# Airflow vars
variables: {{}}
        """
        settings_file.write_text(file_contents.strip())

    # Initialize the .env file
    env_file = Path(project_dir / ".env")
    if not env_file.exists():
        file_contents = f"""
AIRFLOW_HOME={project_dir}
AIRFLOW__CORE__LOAD_EXAMPLES=False
AIRFLOW__CORE__EXECUTOR=LocalExecutor
"""
        env_file.write_text(file_contents.strip())
    typer.echo(f"Airflow project initialized in {project_dir}")


def get_latest_airflow_version(verbose: bool = False) -> str:
    try:
        with httpx.Client() as client:
            response = client.get("https://pypi.org/pypi/apache-airflow/json")
            data = response.json()
            latest_version = data["info"]["version"]
            if verbose:
                print(f"Latest Apache Airflow version detected: [bold cyan]{latest_version}[/bold cyan]")
            return latest_version
    except (httpx.RequestError, KeyError) as e:
        if verbose:
            print(f"[bold red]Error occurred while retrieving latest version: {e}[/bold red]")
            print("[bold yellow]Defaulting to Apache Airflow version 2.7.0[/bold yellow]")
        return "2.7.0"


@app.command()
def init(
    project_name: str = typer.Argument(
        ...,
        help="Name of the Airflow project to be initialized.",
    ),
    airflow_version: str = typer.Option(
        default=get_latest_airflow_version(verbose=True),
        help="Version of Apache Airflow to be used in the project. Defaults to latest.",
    ),
    python_version: str = typer.Option(
        default=f"{sys.version_info.major}.{sys.version_info.minor}",
        help="Version of Python to be used in the project.",
    ),
):
    """
    Initialize a new Airflow project.
    """
    create_project(project_name, airflow_version, python_version)


def verify_or_create_venv(venv_path: str | Path, recreate: bool):
    venv_path = os.path.abspath(venv_path)

    if recreate and os.path.exists(venv_path):
        print(f"Recreating virtual environment at [bold blue]{venv_path}[/bold blue]")
        shutil.rmtree(venv_path)

    venv_bin_python = os.path.join(venv_path, "bin", "python")
    if os.path.exists(venv_path) and not os.path.exists(venv_bin_python):
        print(f"[bold red]Virtual environment at {venv_path} does not exist or is not valid.[/bold red]")
        raise SystemExit()

    if not os.path.exists(venv_path):
        venv.create(venv_path, with_pip=True)
        print(f"Virtual environment created at [bold blue]{venv_path}[/bold blue]")

    return venv_path


def is_airflow_installed(venv_path: str) -> bool:
    venv_bin_python = os.path.join(venv_path, "bin", "python")
    if not os.path.exists(venv_bin_python):
        return False

    try:
        subprocess.run([venv_bin_python, "-m", "airflow", "version"], check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        return False


def install_airflow(
    version: str,
    venv_path: str,
    constraints_url: str,
    extras: str = "",
    requirements: str = "",
    verbose: bool = False,
):
    if is_airflow_installed(venv_path):
        print(
            f"[bold yellow]Apache Airflow {version} is already installed. Skipping installation.[/bold yellow]"
        )
        return

    venv_bin_python = os.path.join(venv_path, "bin", "python")
    if not os.path.exists(venv_bin_python):
        print(f"[bold red]Virtual environment at {venv_path} does not exist or is not valid.[/bold red]")
        raise SystemExit()

    upgrade_pipeline_command = f"{venv_bin_python} -m pip install --upgrade pip setuptools wheel"

    install_command = f"{upgrade_pipeline_command} && {venv_bin_python} -m pip install 'apache-airflow=={version}{extras}' --constraint {constraints_url}"

    if requirements:
        install_command += f" -r {requirements}"

    try:
        if verbose:
            print(f"Running command: [bold]{install_command}[/bold]")
        subprocess.run(install_command, shell=True, check=True)
        print(f"[bold green]Apache Airflow {version} installed successfully![/bold green]")
        print(f"Virtual environment at {venv_path}")
    except subprocess.CalledProcessError:
        print("[bold red]Error occurred during installation.[/bold red]")
        raise SystemExit()


def _get_conf_or_raise(key: str, settings: dict) -> str:
    if key not in settings:
        typer.echo(f"Key '{key}' not found in settings file.")
        raise typer.Exit(1)
    return settings[key]


@app.command()
def build(
    project_path: Path = typer.Argument(Path.cwd(), help="Absolute path to the Airflow project directory."),
    settings_file: Path = typer.Option(
        Path.cwd() / SETTINGS_FILENAME,
        help="Path to the settings file.",
    ),
    venv_path: Path = typer.Option(
        Path.cwd() / ".venv",
        help="Path to the virtual environment.",
    ),
    recreate_venv: bool = typer.Option(
        False,
        help="Recreate virtual environment if it already exists.",
    ),
):
    project_path = Path(project_path).absolute()
    settings_file = Path(settings_file).absolute()

    if not Path(project_path / SETTINGS_FILENAME).exists():
        typer.echo(f"Settings file '{settings_file}' not found.")
        raise typer.Exit(1)

    with open(settings_file) as f:
        config = yaml.safe_load(f)

    airflow_version = _get_conf_or_raise("airflow_version", config)
    python_version = _get_conf_or_raise("python_version", config)
    constraints_url = f"https://raw.githubusercontent.com/apache/airflow/constraints-{airflow_version}/constraints-{python_version}.txt"

    # Create virtual environment
    venv_path = verify_or_create_venv(venv_path, recreate_venv)

    # Install Airflow and dependencies
    install_airflow(
        version=airflow_version,
        venv_path=venv_path,
        constraints_url=constraints_url,
    )

    typer.echo("Airflow project built successfully.")


def source_env_file(env_file: str):
    try:
        load_dotenv(env_file)
    except Exception as e:
        typer.echo(f"Error loading .env file: {e}")
        raise typer.Exit(1)


def activate_virtualenv(venv_path: str):
    if os.name == "posix":
        bin_path = os.path.join(venv_path, "bin", "activate")
        activate_cmd = f"source {bin_path}"
    elif os.name == "nt":
        bin_path = os.path.join(venv_path, "Scripts", "activate")
        activate_cmd = f"call {bin_path}"
    else:
        typer.echo("Unsupported operating system.")
        raise typer.Exit(1)

    return activate_cmd


@app.command()
def start(
    project_path: str = typer.Argument(..., help="Absolute path to the Airflow project directory."),
):
    config_file = os.path.join(project_path, "config.yaml")
    env_file = os.path.join(project_path, ".env")

    if not os.path.exists(config_file):
        typer.echo(f"Config file '{config_file}' not found.")
        raise typer.Exit(1)

    if not os.path.exists(env_file):
        typer.echo(".env file not found.")
        raise typer.Exit(1)

    with open(config_file) as f:
        config = yaml.safe_load(f)

    # Source the .env file to set environment variables
    source_env_file(env_file)
    os.environ["AIRFLOW_HOME"] = project_path
    os.environ["AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"] = "sqlite:///" + os.path.abspath(
        os.path.join(project_path, "airflow.db")
    )

    venv_path = os.path.abspath(
        config.get(
            "venv_path",
            os.path.join(
                project_path,
                f".venv/airflow_{config.get('airflow_version')}_py{config.get('python_version')}",
            ),
        )
    )
    activate_cmd = activate_virtualenv(venv_path)

    try:
        # Activate the virtual environment and then run the airflow command
        subprocess.run(f"{activate_cmd} && airflow standalone", shell=True, check=True, env=os.environ)
    except subprocess.CalledProcessError as e:
        typer.echo(f"Error starting Airflow: {e}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
