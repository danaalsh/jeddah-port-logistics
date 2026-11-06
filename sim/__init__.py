"""Port-to-destination logistics model for the Jeddah port project.

data     download inputs from the repository's data-latest release
network  GCC road graph with truck costs and border-crossing delays; road routing
sea      sea legs from origin regions to ports, with chokepoint closures
model    scenario runs: cheapest port and route for each origin and destination
"""
