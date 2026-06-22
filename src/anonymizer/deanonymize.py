from .mappings import AnonymizationMappings


def deanonymize(text: str, mappings: AnonymizationMappings) -> str:
    reverse = mappings.as_reverse_map()
    # Dłuższe placeholdery najpierw, żeby [IMIĘ_10] nie był podmieniony przez [IMIĘ_1]
    for placeholder in sorted(reverse, key=len, reverse=True):
        text = text.replace(placeholder, reverse[placeholder])
    return text
