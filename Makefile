META = meta

.PHONY: all clean

all: $(META)/electron-index.json $(META)/packages-meta-ext-v1.json $(META)/aur-packages $(META)/homebrew-casks.json

$(META):
	mkdir -p $(META)

$(META)/electron-index.json: | $(META)
	curl -fsSL https://artifacts.electronjs.org/headers/dist/index.json -o $@

$(META)/packages-meta-ext-v1.json: | $(META)
	curl -fsSL https://aur.archlinux.org/packages-meta-ext-v1.json.gz | gunzip > $@

$(META)/aur-packages: | $(META)
	curl -fsSL https://aur.archlinux.org/packages.gz | gunzip > $@

$(META)/homebrew-casks.json: | $(META)
	curl -fsSL https://formulae.brew.sh/api/cask.json -o $@

clean:
	rm -f $(META)/electron-index.json $(META)/packages-meta-ext-v1.json $(META)/aur-packages $(META)/homebrew-casks.json
