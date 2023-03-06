#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# Replacing non-break spaces by break spaces and
# inserting <wbr>-tags in long text areas without spaces.
#
#
# This parser loops over DOM tree and counts the number
# of chars without a word breaking character (' ', '\n', '\r')
# in the data areas
#
# Notes: - Opening/closing tags do not reset the counter, because
#          w.l.o.g. aaa<b>ccc</b> do not breaking the word.
#        - handle_comment, handle_entityref and handle_charref-calls will split handling
#          of text in multiple sections.
#          Thus, 'aaa&nbsp;ccc' will call handle_data for 'aaa' and 'ccc'


from html.parser import HTMLParser
# from html.entities import name2codepoint

from io import StringIO
from enum import Enum
from dataclasses import dataclass

import logging
logger = logging.getLogger(__name__)


class TextType(Enum):
    TAG = 0
    DATA = 1
    BREAK = 2  # tag/entityref/charref allowing line break

@dataclass
class Token:
    type: TextType = TextType.TAG
    value: str = ""

# Marker for inserting <wbr> Tag at beginning of token
@dataclass
class InsertWbr:
    iToken: int # Token index

# Marker for splitting token part. (At least at the end of the part we will add a <wbr>)
@dataclass
class InsertSplit:
    iToken: int # Token index
    lindex: int # range [lindex:rindex]
    rindex: int #

class WordBreaker(HTMLParser):
    MAX_CHARS_WITHOUT_SPACE = 50
    WORD_BREAKING_CHARS = ' \n\r'
    WORD_BREAKING_TAGS = ["wbr", "br"]  # <tag>
    WORD_BREAKING_ENTITYREFS = [  # &<name>;
                                "ZeroWidthSpace",
                                "NegativeThickSpace",
                                "NegativeMediumSpace",
                                "NegativeThinSpace",
                                "NegativeVeryThinSpace"
                                ]
    WORD_BREAKING_CHARREFS = [  # &#<number>;
                              "8203",
                              "x200B",
                              ]

    TRANSLATE_UNICODE_SPACES = str.maketrans({
        " ": " ",  # U+00A0 (NO-BREAK SPACE) => U+0020 (SPACE)
        " ": " ",  # U+202F (NARROW NO-BREAK SPACE) => U+2005 (FOUR-PER-EM SPACE)
        "﻿": "​",  # U+FEFF (ZERO WIDTH NO-BREAK SPACE) => U+200B (ZERO WIDTH SPACE)
    })

    # Threated like TRANSLATE_UNICODE_SPACES
    TRANSLATE_ENTRYREFS = {
        "&nbsp;": " "
    }

    # Threated like TRANSLATE_UNICODE_SPACES
    TRANSLATE_CHARREFS = {
    }

    def __init__(self, max_chars=MAX_CHARS_WITHOUT_SPACE):
        super().__init__()
        self.convert_charrefs = False
        self.max_chars_without_space = max_chars

        # Stores tuples (TextType, Text) where Text is <this...> (TAG),
        # or others (DATA, BREAK)
        # Before output is returned the DATA-Nodes can be searched
        # for long non-broken chunks of chars.
        self.tokens = []

        # Add dummy to avoid empty list
        self.tokens.append(Token(TextType.DATA, ""))

    # Begin of Parser's handler defnitions

    def handle_starttag(self, tag, attrs):
        textType = TextType.BREAK if tag in self.WORD_BREAKING_TAGS else TextType.TAG
        self.tokens.append(Token(textType, self.get_starttag_text()))

    def handle_startendtag(self, tag, attrs):
        textType = TextType.BREAK if tag in self.WORD_BREAKING_TAGS else TextType.TAG
        self.tokens.append(Token(textType, self.get_starttag_text()))

    def handle_endtag(self, tag):
        self.tokens.append(Token(TextType.TAG, f"</{tag}>"))

    def handle_data(self, data):
        self.tokens.append(Token(TextType.DATA, data))
        """
        if self.tokens[-1].type == TextType.DATA:  # Merge with previous token
            self.tokens[-1].value = f"{self.tokens[-1].value}{data};"
        else:
            self.tokens.append(Token(TextType.DATA, data))
        """

    def handle_comment(self, data):
        self.tokens.append(Token(TextType.TAG, f"<!--{data}-->"))

    def handle_entityref(self, name):
        if name in self.WORD_BREAKING_ENTITYREFS:
            self.tokens.append(Token(TextType.BREAK, f"&{name};"))
        elif self.tokens[-1].type == TextType.DATA:  # Merge with previous token
            self.tokens[-1].value = f"{self.tokens[-1].value}&{name};"
        else:
            self.tokens.append(Token(TextType.DATA, f"&{name};"))
        # c = chr(name2codepoint[name])
        # print("Named ent:", c)

    def handle_charref(self, name):
        if name in self.WORD_BREAKING_CHARREFS:
            self.tokens.append(Token(TextType.BREAK, f"&#{name};"))
        elif self.tokens[-1].type == TextType.DATA:  # Merge with previous token
            self.tokens[-1].value = f"{self.tokens[-1].value}&#{name};"
        else:
            self.tokens.append(Token(TextType.DATA, f"&#{name};"))

        # if name.startswith('x'):
        #     c = chr(int(name[1:], 16))
        # else:
        #     c = chr(int(name))
        #     print("Num ent  :", c)

    def handle_decl(self, data):
        self.tokens.append(Token(TextType.TAG, f"<!{data}>"))

    # End of parser's handler definitions

    def getvalue(self):
        out = StringIO()
        self.write(out)
        return out.getvalue()

    def write(self, f):
        for token in self.tokens:
            f.write(token.value)

    # The real work begins here.
    def break_words(self):
        """
          Token 1  |   Token 2  |   Token 3 |
             \n=======================\n
             ^                        ^
             Last breaking char       breaking char after at least MAX_CHARS_WITHOUT_SPACE
               [ Range for splitting ]
        """

        num_chars_after_last_break_first = 0  # Just first token
        num_chars_after_last_break_all = 0    # Sum over all token
        last_token_index = 0 # Index of token which first character
                             # for num_chars_after_last_break holds
        lsplits = []  # Collecting positions for wbr/split inserting

        for iToken in range(len(self.tokens)):
            token = self.tokens[iToken]

            if token.type == TextType.TAG:
                continue

            if token.type == TextType.BREAK:
                num_chars_after_last_break_first = 0
                num_chars_after_last_break_all = 0
                last_token_index = iToken
                continue

            # TextType.DATA case
            num_chars_after_last_break_all += len(token.value)
            if num_chars_after_last_break_all <= self.max_chars_without_space:
                continue

            # Now, the next breaking char might be far away from previous.
            # Searching for splitting points
            (num_chars_after_last_break_first, last_token_index) =\
                self._search_split_char(
                    last_token_index, num_chars_after_last_break_first,
                    iToken, lsplits)
            num_chars_after_last_break_all = num_chars_after_last_break_first

        self._inserting_splits(lsplits)

    def _search_split_char(self, last_token_index, num_after, next_token_index,
                           lsplits):
        assert(last_token_index < next_token_index)
        current_token_index = last_token_index + 1

        while current_token_index <= next_token_index:
            # Search most right break. If not too far away from left,
            # we can proceed with the next token
            # Three ranges A,B, and C:
            #   (Token last)     (       Token i         )    (Token next)
            #   -num_after    .... [lindex] .... [rindex] ... |
            #        [AAAAAAAAAAAAA]      [BBBBB]       [CCCCCCCCCCCCCCCC]
            #
            # • last < i <= next
            # • lindex left most break character in Token i
            # • rindex right most break character in Token i
            # • range A spans from Token last to Token i.
            # • range B is inside of one Token (i). Length of B can be zero.
            # • range C will not be processed, but new num_after is len(Token i)-rindex

            token = self.tokens[current_token_index]
            if token.type != TextType.DATA:
                current_token_index += 1
                continue

            rindex_break, lindex_break = None, None
            try:
                rindex_break = rindex(token.value,
                                      self.WORD_BREAKING_CHARS)
                lindex_break = index(token.value,
                                      self.WORD_BREAKING_CHARS,
                                      0, rindex_break)
            except ValueError:
                current_token_index += 1
                continue

            # Process range A
            if num_after + lindex_break > self.max_chars_without_space:
                # Insert split at beginning of current token.
                # Characters left of split satisfy MAX_CHARS_WITHOUT_SPACE-condition
                # because otherwise the break_words()-function had triggered earlier. (*)
                # We shifting Range A-Elements into Range B to handle the case that
                # len(Range A) > self.max_chars_without_space
                lsplits.append(InsertWbr(current_token_index))
                lindex_break = 0
            else:
                # Nothing to do for range A :top:
                pass

            # Process range B
            if rindex_break - lindex_break > self.max_chars_without_space:
                lsplits.append(
                    InsertSplit(current_token_index,
                                lindex_break+1,
                                rindex_break)
                )

            # Process range C
            num_after = len(token.value) - rindex_break - 1
            last_token_index = current_token_index

            if num_after > self.max_chars_without_space:
                assert(current_token_index == next_token_index)
                # Big range C. Threat it like big B and zero-with C
                lsplits.append(
                    InsertSplit(current_token_index, rindex_break+1, len(token.value))
                )
                num_after = 0

            # Restarting loop not required? (see *)
            # return (num_after, last_token_index)
            current_token_index += 1

        if rindex_break is None:
            # This part is only reached if ValueError raised in last loop step.
            # • Join of tokens [last_token_index, next_token_index-1] are not too wide.
            #   We can simply insert a <wbr> after them and threat whole token
            #   like range C or B (depending on it's length).
            lsplits.append(InsertWbr(next_token_index))
            num_after = len(self.tokens[next_token_index].value)
            last_token_index = next_token_index
            if num_after > self.max_chars_without_space:
                # Range C empty
                lsplits.append(
                    InsertSplit(next_token_index, 0, num_after)
                )
                num_after = 0
            else:
                # Range B emtpy
                pass

        return (num_after, last_token_index)


    def _inserting_splits(self, lsplits):
        # This updates self.tokens list and need a reversed looping
        # to keep the indizes valid.
        for s in lsplits.__reversed__():
            if isinstance(s, InsertWbr):
                self.tokens.insert(s.iToken,
                                   Token(TextType.TAG, "<wbr/>"))
            if isinstance(s, InsertSplit):
                token = self.tokens[s.iToken]
                text = token.value[s.lindex:s.rindex]

                # Soft breaks
                text.translate(self.TRANSLATE_UNICODE_SPACES)
                for (k,v) in self.TRANSLATE_ENTRYREFS.items():
                    text = text.replace(k,v)
                for (k,v) in self.TRANSLATE_CHARREFS.items():
                    text = text.replace(k,v)

                # Hard breaks.
                if True:
                    trenner = list(self.WORD_BREAKING_CHARS)
                    trenner.extend(list(self.TRANSLATE_UNICODE_SPACES.values()))
                    text = self._split_after_n_chars(text, trenner, self.max_chars_without_space)

                # token.value = f"{token.value[:s.lindex]}»{text}«{token.value[s.rindex:]}"
                token.value = f"{token.value[:s.lindex]}{text}{token.value[s.rindex:]}"

                # Break after token (not required) 
                #self.tokens.insert(s.iToken+1,
                #                   Token(TextType.TAG, "<wbr/>"))


    def _split_after_n_chars(self, text, trenner, width):
        icurrent = 0
        len_text = len(text)
        wide_ranges = []
        inext = -1
        while True:
            try:
                # print(f"{icurrent}, {inext} {width} {text[icurrent:]}")
                # inext = text.rindex(trenner[0], icurrent+1, icurrent+width)
                inext = rindex(text, trenner, start=icurrent+1, end=icurrent+width)
            except ValueError:
                if icurrent + width >= len_text:
                    break
                else:
                    wide_ranges.append((icurrent, icurrent+width))
                    icurrent += width
            else:
                icurrent = inext+1

        if len(wide_ranges) == 0:
            return text

        out = StringIO()
        e = 0
        # logger.debug(f"Breaking string\n'{text}'")
        for w in wide_ranges:
            s = w[0]
            out.write(text[e:s])
            e = w[1]
            out.write(text[s:e])
            out.write("<wbr/>")
            #out.write("&ZeroWidthSpace;")
            #out.write("§")

        out.write(text[e:])
        # logger.debug(f" ===========>\n'{out.getvalue()}'")
        return out.getvalue()

# =====================================================

def index(s, subs, start=0, end=None):
    """ Return lowest index of substitution in subs or raise ValueError.

    Similar to str.index(sub)
    """
    l = len(s)
    if end is None:
        end = l
    end = end if end > -1 else l + end
    start = start if start > -1 else l + start
    lowest = l
    for sub in subs:
        try:
            lowest = s.index(sub, start, end)
            if lowest == start:
                break

            end = lowest-1  # No neg. value because lowest > start
        except ValueError:
            pass
    pass

    if lowest == l:
        raise ValueError("No substring found")

    return lowest

def rindex(s, subs, start=0, end=None):
    """ Return highest index of substitution in subs or raise ValueError.

    Similar to str.rindex(sub)
    """
    l = len(s)
    if end is None:
        end = l
    end = end if end > -1 else l + end
    start = start if start > -1 else l + start
    highest = -1
    for sub in subs:
        try:
            highest = s.rindex(sub, start, end)
            if highest == end:
                break

            start = highest+1
        except ValueError:
            pass
    pass

    if highest == -1:
        raise ValueError("No substring found")

    return highest

# ======================== Tests ======================
class TestException(Exception):
    pass

def _index(s, subs, *largs):
    l = []
    for sub in subs:
        try:
            i = s.index(sub, *largs)
        except ValueError:
            continue
        l.append(i)

    if l:
        return min(l)

    return None

def _rindex(s, subs, *largs):
    # For call of str.index or str.rindex
    l = []
    for sub in subs:
        try:
            i = s.rindex(sub, *largs)
        except ValueError:
            continue
        l.append(i)

    if l:
        return max(l)
    return None

def _compare(fname1, fname2, s, subs, *largs):
    # Compare str.index vs. index and str.rindex vs rindex

    # Return value of new function
    try:
        i1 = globals()[fname1](s, subs, *largs)
    except ValueError:
        i1 = None

    # Return value of normal function
    i2 = globals()[fname2](s, subs, *largs)

    ret = (i1 == i2)
    #if not ret:
    #    import pdb; pdb.set_trace()

    return ret

def _test(fname1, fname2):
    subs1 = "adg"
    subs2 = ["ab", "gg"]
    match1 = "abcdefg"
    match2 = "oooggooo"
    no_match = "xyzuvw"

    f1 = globals()[fname1]

    if not _compare(fname1, fname2, match1, subs1):
        raise TestException()

    if not _compare(fname1, fname2, match1, subs1[2]):
        raise TestException()

    if not _compare(fname1, fname2, match2, subs2):
        raise TestException()

    for s in range(-3, 3):
        if not _compare(fname1, fname2, match1, subs1, s):
            print(f"No match for {fname1}('{match1}', '{subs1}', start={s})")
            raise TestException()

    for s in range(-3, 3):
        for e in range(-3, 3):
            if s >= e:
                continue
            if not _compare(fname1, fname2, match1, subs1, s, e):
                print(f"No match for {fname1}('{match1}', '{subs1}', start={s}, end={e})")
                raise TestException()

    try:
        f1(no_match, subs1)
        raise TestException()
    except ValueError:
        pass

    for s in range(-3, 3):
        try:
            f1(no_match, subs2, s)
            raise TestException()
        except ValueError:
            pass

    for s in range(-3, 3):
        for e in range(-3, 3):
            if s >= e:
                continue
            try:
                f1(no_match, subs1, s, e)
                raise TestException()
            except ValueError:
                pass

    return True

def test_index():
    return _test("index", "_index")

def test_rindex():
    return _test("rindex", "_rindex")

def test_parser_projection():
    parser = WordBreaker()

    projection_text = '''\
        <!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN" "http://www.w3.org/TR/html4/strict.dtd">
    <div id="foo" test='"' bar="'">
    <div dir="ltr" class="a BB">
    <h2><a href="/">Header</a></h2>
    <br /> &#x3E; &gt;
    </div>
    '''

    parser.feed(projection_text)
    projection_out = parser.getvalue()
    if not projection_text == projection_out:
        logger.error("Error: projection_text was changed by parser")
        logger.error(projection_out)
        return False

    return True

def test_parser_split():
    parser = WordBreaker()

    long_lines_text = '''\
    <!-- Insert breaking chars into long line-->
    COMMENTaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa<!-- Comment --><b>aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa</b>
    SPACEaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa <b>aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa</b>
    NBSP;bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb&nbsp;<b>bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb</b>
    UNICODE_NO_BREAK_SPACEcccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc <b>ccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc</b>
    UNICODE_NARROW_NO_BREAK_SPACEddddddddddddddddddddddddddddddddddddddddddddddddddddddddd <b>ddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd</b>
    UNICODE_ZERO_WIDTH_NO_BREAK_SPACEeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee﻿<b>eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee</b>
    UNUSEDffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff<b>fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff</b>
    '''

    parser.feed(long_lines_text)
    parser.break_words()  # Resolving long lines problem
    long_lines_out = parser.getvalue()
    print(long_lines_out)

    return True


def run_tests():
    tests = [
        "index",
        "rindex",
        "parser_projection",
        "parser_split",
    ]
    ok = True
    for fname in tests:
        if globals()["test_"+fname]():
            print(f"Test '{fname}' succeeded!")
        else:
            print(f"Test '{fname}' failed!")
            ok = False

    return ok


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    run_tests()
