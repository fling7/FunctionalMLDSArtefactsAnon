"""Reviewed offline numbers adapter; dependency registry supplies exact inputs."""
from repro.make_numbers import main
if __name__=="__main__":
    main(sealed_offline=True)
