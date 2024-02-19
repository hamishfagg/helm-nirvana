import iterfzf
import typer
from rich.prompt import Prompt
from rich import print
from rich.table import Table
import os
import re
import subprocess
import yaml

app = typer.Typer()
r_values_files = re.compile("values-.*\.ya?ml")


def find_services():
    here_dirs = [d for d in os.listdir('.') if os.path.isdir(d)]
    if "deployment" in here_dirs:  # there is a "deployment" dir in the current dir
        os.chdir("./deployment")

    # get dirs that looks like they could be for service helm charts
    service_dirs = [d for d in os.listdir(".") if os.path.isdir(d)]
    return [d for d in service_dirs if any(r_values_files.match(f) for f in os.listdir(d))]


def find_envs(service_name):
    files = [f for f in os.listdir(service_name) if r_values_files.match(f)]
    return [f.split("-", 1)[1].split(".")[0] for f in files]


def check_requirements():
    # kubens
    # helm
    # check we're logged into a cluster and print the cluster name for the user to check
    pass


def main(namespace: str = None, service_name: str = None, env_name: str = None, image_tag: str = None):
    check_requirements()

    # Run this to get k8s namespaces in the background while we do everything else
    # We don't need to do this if the user has already specified a namespace via CLI
    if namespace is None:
        sub_namespaces = subprocess.Popen(["kubens"], shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if service_name is None:
        services = find_services()
        service_name = iterfzf.iterfzf(services, prompt="Service to deploy > ")

    # We now have a service name so we can get helm to update dependencies in the background
    depends_updater = subprocess.Popen([f"helm dependencies update {service_name}"], shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if namespace is None:
        namespaces = sub_namespaces.communicate()[0].split("\n")
        namespace = iterfzf.iterfzf(namespaces, prompt="Target namespace > ")

    # We now have a namespace and a service so we can ask helm for chart values in the background
    # Again, only if the user didn't specify an image tag via CLI
    if image_tag is None:
        sub_values = subprocess.Popen([f"helm get values --namespace {namespace} {service_name}"], shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if env_name is None:
        envs = find_envs(service_name)
        # If the selected namespace also names an env, make that the first option
        if namespace in envs:
            envs.insert(0, envs.pop(envs.index(namespace)))
        env_name = iterfzf.iterfzf(envs, prompt="Target env > ")

    if image_tag is None:
        values = sub_values.communicate()[0]  # Wait for the helm command to complete
        values = yaml.safe_load(values) if sub_namespaces.returncode == 0 and values else {}  # If the helm command failed, we can't suggest any tags
        image_tag = values.get("global", {}).get("image", {}).get("tag", "latest")

        # Get an image tag from the user (default to the one we just got from helm)
        image_tag = Prompt.ask("Image tag:", default=image_tag)

    # We now have all the info we need to do the upgrade
    table = Table(show_header=False)
    table.add_column(style="bold")
    table.add_row("Service", service_name)
    table.add_row("Namespace", namespace)
    table.add_row("Environment", env_name)
    table.add_row("Image Tag", image_tag)
    print(table)

    # Wait for the dependency update to finish
    if depends_updater.poll() is None:
        print("Waiting for helm dependency update to finish...")
    depends_err = depends_updater.communicate()[1]
    if depends_updater.returncode != 0:
        raise typer.Exit("Helm dependency update failed:\n" + depends_err)

    # Run helm diff and just print the output to console
    print("\n[bold]----- HELM DIFF OUTPUT ----[/bold]\n")
    subprocess.Popen([f"helm diff upgrade --namespace {namespace} --allow-unreleased {service_name} {service_name} -f {service_name}/values.yaml -f {service_name}/values-{env_name}.yaml --set global.namespace=\"{namespace}\" --set global.image.tag=\"{image_tag}\""], shell=True).communicate()
    print("\n[bold]----- HELM DIFF OUTPUT -----[/bold]\n")

    cont = typer.confirm("Do the above changes look correct?")
    if not cont:
        raise typer.Abort()

    # Do the upgrade
    print("\n[bold]--- RUNNING HELM UPGRADE ---[/bold]\n")
    subprocess.Popen([f"helm upgrade --install --namespace {namespace} {service_name} {service_name} -f {service_name}/values.yaml -f {service_name}/values-{env_name}.yaml --set global.namespace=\"{namespace}\" --set global.image.tag=\"{image_tag}\""], shell=True).communicate()


if __name__ == "__main__":
    typer.run(main)
