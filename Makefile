FILENAME=lightning
TITLE=title.txt

DEF_TARGETS=lightning.epub lightning.pdf
TARGETS=$(DEF_TARGETS) lightning.mobi
MDS=$(sort $(wildcard *-*.md))

all: $(DEF_TARGETS)

$(FILENAME).%: $(TITLE) $(MDS)
	pandoc -S -o $@ $^

$(FILENAME).mobi: $(FILENAME).epub
	ebook-convert $< $@

clean:
	rm -f $(TARGETS)

.PHONY: clean
