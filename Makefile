FILENAME=lightning
TITLE=title.txt

PANDOC_OPTS=-sS
PANDOC_PDF_OPTS=$(PANDOC_OPTS) -V geometry:margin=1.5in

DEF_TARGETS=$(FILENAME).epub $(FILENAME).pdf
TARGETS=$(DEF_TARGETS) $(FILENAME).mobi $(FILENAME).man
MDS=$(sort $(wildcard *-*.md))

all: $(DEF_TARGETS)

man: $(FILENAME).man FAKE
	@man ./$(FILENAME).man

$(FILENAME).pdf: $(TITLE) $(MDS)
	pandoc $(PANDOC_PDF_OPTS) -o $@ $^

$(FILENAME).man: $(TITLE) $(MDS)
	pandoc $(PANDOC_OPTS) -o $@ -t man $^

$(FILENAME).epub: $(TITLE) $(MDS)
	pandoc $(PANDOC_OPTS) -o $@ $^

$(FILENAME).mobi: $(FILENAME).epub
	ebook-convert $< $@

clean:
	rm -f $(TARGETS)

.PHONY: clean FAKE
