#!/usr/bin/env python3
"""
Tool for merging TR VCF files generated by
the same TR genotyper.
"""

import argparse
import os
import sys
from typing import List

import cyvcf2
import numpy as np

import trtools.utils.common as common
import trtools.utils.mergeutils as mergeutils
import trtools.utils.tr_harmonizer as trh
import trtools.utils.utils as utils
from trtools import __version__


NOCALLSTRING = "."

# Tool-specific fields to merge. (FIELDNAME, req'd). req'd is True if merge should
# fail when all records don't have identical values for that field
INFOFIELDS = {
    trh.VcfTypes.gangstr: [("END", True), ("RU", True), ("PERIOD", True), ("REF", True), \
                ("EXPTHRESH", True), ("STUTTERUP", False), \
                ("STUTTERDOWN", False), ("STUTTERP", False)],
    trh.VcfTypes.hipstr: [("INFRAME_PGEOM", False), ("INFRAME_UP", False), ("INFRAME_DOWN", False), \
               ("OUTFRAME_PGEOM", False), ("OUTFRAME_UP", False), ("OUTFRAME_DOWN", False), \
               ("BPDIFFS", False), ("START", True), ("END", True), ("PERIOD", True), \
               ("AN", False), ("REFAC", False), ("AC", False), ("NSKIP", False), \
               ("NFILT", False), ("DP", False), ("DSNP", False), ("DSTUTTER", False), \
               ("DFLANKINDEL", False)],
    trh.VcfTypes.eh: [("END", True), ("REF", True), ("REPID", True), ("RL", True), \
           ("RU", True), ("SVTYPE", False), ("VARID", True)],
    trh.VcfTypes.popstr: [("Motif", True)], # TODO ("RefLen", True) omitted. since it is marked as "A" incorrectly
    trh.VcfTypes.advntr: [("END", True), ("VID", True), ("RU", True), ("RC", True)]
}

# Tool-specific format fields to merge
# Not all fields currently handled
# If not listed here, it is ignored
FORMATFIELDS = {
    trh.VcfTypes.gangstr: ["DP","Q","REPCN","REPCI","RC","ENCLREADS","FLNKREADS","ML","INS","STDERR","QEXP"],
    trh.VcfTypes.hipstr: ["GB","Q","PQ","DP","DSNP","PSNP","PDP","GLDIFF","DSTUTTER","DFLANKINDEL","AB","FS","DAB","ALLREADS","MALLREADS"],
    trh.VcfTypes.eh: ["ADFL","ADIR","ADSP","LC","REPCI","REPCN","SO"],
    trh.VcfTypes.popstr: ["AD","DP","PL"],
    trh.VcfTypes.advntr: ["DP","SR","FR","ML"]
}

def WriteMergedHeader(vcfw, args, readers, cmd, vcftype):
    r"""Write merged header for VCFs in args.vcfs

    Also do some checks on the VCFs to make sure merging
    is appropriate.
    Return info and format fields to use

    Parameters
    ----------
    vcfw : file object
       Writer to write the merged VCF
    args : argparse namespace
       Contains user options
    readers : list of vcf.Reader
       List of readers to merge
    cmd : str
       Command used to call this program
    vcftype : str
       Type of VCF files being merged

    Returns
    -------
    useinfo : list of (str, bool)
       List of (info field, required) to use downstream
    useformat: list of str
       List of format field strings to use downstream
    """
    def get_header_lines(field, reader):
        compare_len = 3 + len(field)
        compare_start = '##' + field.lower() + "="
        return [line for line in reader.raw_header.split('\n') if \
                line[:compare_len].lower() == compare_start]

    # Check contigs the same for all readers
    contigs = get_header_lines('contig', readers[0])
    for i in range(1, len(readers)):
        if get_header_lines('contig', readers[i]) != contigs:
            raise ValueError(
                "Different contigs (or contig orderings) found across VCF "
                "files. Make sure all files used the same reference. "
                "Consider using this command:\n\t"
                "bcftools reheader -f ref.fa.fai file.vcf.gz -o file_rh.vcf.gz")
    # Write VCF format, commands, and contigs
    vcfw.write("##fileformat=VCFv4.1\n")

    # Update commands
    for r in readers:
        for line in get_header_lines('command', r):
            vcfw.write(line + '\n')
    vcfw.write("##command="+cmd+"\n")

    # Update sources
    sources = set.union(*[set(get_header_lines('source', reader)) for reader in readers])
    for src in sources:
        vcfw.write(src+"\n")

    for contig in contigs:
        vcfw.write(contig + "\n")

    # Write ALT fields if present
    alts = set.union(*[set(get_header_lines('alt', reader)) for reader in readers])
    for alt in alts:
        vcfw.write(alt+'\n')

    # Write INFO fields, different for each tool
    useinfo = []
    infos = get_header_lines('info', readers[0])
    for (field, reqd) in INFOFIELDS[vcftype]:
        this_info = [line for line in infos if 'ID=' + field + ',' in line]
        if len(this_info) == 0:
            common.WARNING("Expected info field %s not found. Skipping"%field)
        elif len(this_info) >= 2:
            common.WARNING("Found two header lines matching the info field %s. Skipping"%field)
        else:
            vcfw.write(this_info[0] + '\n')
            useinfo.append((field, reqd))

    # Write GT header
    vcfw.write("##FORMAT=<ID=GT,Number=1,Type=String,Description=\"Genotype\">\n")
    # Write FORMAT fields, different for each tool
    useformat = []
    formats = get_header_lines('format', readers[0])
    for field in FORMATFIELDS[vcftype]:
        this_format = [line for line in formats if 'ID=' + field + ',' in line]
        if len(this_format) == 0:
            common.WARNING("Expected format field %s not found. Skipping"%field)
        elif len(this_format) >= 2:
            common.WARNING("Found two header lines matching the format field %s. Skipping"%field)
        else:
            vcfw.write(this_format[0] + '\n')
            useformat.append(field)

    # Write sample list
    try:
        if not args.update_sample_from_file:
            samples = mergeutils.GetSamples(readers)
        else:
            filenames = [fname.split('/')[-1] for fname in args.vcfs.split(',')]
            samples = mergeutils.GetSamples(readers, filenames)
    except ValueError as ve:
        common.WARNING("Error: " + str(ve))
        return None, None
    if len(samples) == 0:
        return None, None
    header_fields = ["CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT"]
    vcfw.write("#"+"\t".join(header_fields+samples)+"\n")
    return useinfo, useformat

def GetRefAllele(current_records, mergelist, trim=False):
    r"""Get reference allele for a set of records

    Parameters
    ----------
    current_records : list of vcf.Record
       List of records being merged
    mergelist : list of bool
       Indicates whether each record is included in merge

    Returns
    -------
    ref : str
       Reference allele string. Set to None if conflicting references are found.
    """
    refs = []
    for i in range(len(mergelist)):
        if mergelist[i]:
            chrom = current_records[i].chrom
            pos = current_records[i].pos
            if not trim:
                refs.append(current_records[i].vcfrecord.REF.upper())
            else:
                refs.append(current_records[i].ref_allele.upper())
    if len(set(refs)) != 1:
        return None
    return refs[0]

def GetAltAlleles(current_records, mergelist, vcftype, trim=False):
    r"""Get list of alt alleles

    Parameters
    ----------
    current_records : list of vcf.Record
       List of records being merged
    mergelist : list of bool
       Indicates whether each record is included in merge
    vcftype :
        The type of the VCFs these records came from

    Returns
    -------
    (alts, mappings) : (list of str, list of np.ndarray)
       alts is a list of alternate allele strings in all uppercase.
       mappings is a list of length equal to the number of
       records being merged. for each record, it is a numpy
       array where an allele with index i in the original
       record has an index of arr[i] in the output merged record.
       (the indecies stored in the arrays are strings for fast
       output) e.g. if the output record has alleles 'A' 'AA,AAA,AAAA'
       and the current record has alleles 'A' 'AAAA,AAA' then
       the mapping for the current record would be np.array(['0', '3', '2'])
    """
    alts = set()
    def get_alts(record):
        if not trim:
            return record.vcfrecord.ALT
        else:
            return record.alt_alleles

    for i in range(len(mergelist)):
        if mergelist[i]:
            ralts = get_alts(current_records[i])
            for item in ralts:
                alts.add(item.upper())
    if vcftype == trh.VcfTypes.eh:
        # EH alleles look like <STR42> where 42 is the
        # number of repeat units so sort accordingly
        out_alts = sorted(alts, key=lambda x: int(x[4:-1]))
    elif vcftype == trh.VcfTypes.popstr:
        # popsr alleles look like <4.2> where 4.2 is the
        # number of repeat units so sort accordingly
        out_alts = sorted(alts, key=lambda x: float(x[1:-1]))
    else:
        out_alts = sorted(alts, key=lambda x: (len(x), x))

    mappings = []
    for i in range(len(mergelist)):
        if mergelist[i]:
            ralts = get_alts(current_records[i])
            mappings.append(
                np.array([0] + [out_alts.index(ralt.upper()) + 1 for ralt in ralts]).astype(str)
            )
    return out_alts, mappings


def GetID(idval):
    r"""Get the ID for a a record

    If not set, output "."

    Parameters
    ----------
    idval : str
       ID of the record

    Returns
    -------
    idval : str
       Return ID. if None, return "."
    """
    if idval is None: return "."
    else: return idval

def GetInfoItem(current_records, mergelist, info_field, fail=True):
    """Get INFO item for a group of records

    Make sure it's the same across merged records
    if fail=True, die if items not the same.
    if fail=False, only do something if we have a rule on how to handle that field

    Parameters
    ----------
    current_records : list of vcf.Record
       List of records being merged
    mergelist : list of bool
       List of indicators of whether to merge each record
    info_field : str
       INFO field being merged
    fail : bool
       If True, throw error if fields don't have same value

    Returns
    -------
    infostring : str
       INFO string to add (key=value)
    """
    if not fail: return None # TODO in future implement smart merging of select fields
    vals = set()
    a_merged_rec = None
    for i in range(len(mergelist)):
        if mergelist[i]:
            a_merged_rec = current_records[i]
            if info_field in current_records[i].info:
                vals.add(current_records[i].info[info_field])
            else:
                raise ValueError("Missing info field %s"%info_field)
    if len(vals)==1:
        return "%s=%s"%(info_field, vals.pop())
    else:
        common.WARNING("Incompatible values %s for info field %s at position "
                       "%s:%i"%(vals, info_field, a_merged_rec.chrom,
                                a_merged_rec.pos))
        return None

def WriteSampleData(vcfw, record, alleles, formats, format_type, mapping):
    r"""Output sample FORMAT data

    Writes a string representation of the GT and other format
    fields for each sample in the record, with tabs
    in between records

    Parameters
    ----------
    vcfw : file
        File to write output to
    record : cyvcf2.Varaint
       VCF record being summarized
    alleles : list of str
       List of REF + ALT alleles
    formats : list of str
       List of VCF FORMAT items
    format_type: list of String
        The type of each format field
    mapping: np.ndarray
        See GetAltAlleles
    """
    assert "GT" not in formats # since we will add that

    genotypes = record.GetGenotypeIndicies()
    not_called_samples = np.all(
        np.logical_or(genotypes[:, :-1] == -1, genotypes[:, :-1] == -2),
        axis=1
    )
    phase_chars = np.array(['/', '|'])[genotypes[:, -1]]

    # pre retrieve all the numpy arrays
    # in case that speeds up performance
    format_arrays = {}
    for format_idx, fmt in enumerate(formats):
        if format_type[format_idx] == 'String':
            format_arrays[fmt] = record.format[fmt]
        elif format_type[format_idx] == 'Float':
            format_arr = record.format[fmt]
            nans = np.isnan(format_arr)
            format_arr = format_arr.astype(str)
            format_arr[nans] = '.'
            format_arrays[fmt] = format_arr
        else:
            format_arrays[fmt] = record.format[fmt].astype(str)

    for sample_idx in range(genotypes.shape[0]):
        vcfw.write('\t')

        if not_called_samples[sample_idx]:
            vcfw.write(".")
            continue

        # Add GT
        vcfw.write(phase_chars[sample_idx].join(
            mapping[genotypes[sample_idx, :-1]]
        ))

        # Add rest of formats
        for fmt_idx, fmt  in enumerate(formats):
            vcfw.write(':')
            if format_type[fmt_idx] == 'String':
                vcfw.write(format_arrays[fmt][sample_idx])
                continue
            else:
                vcfw.write(','.join(
                    format_arrays[fmt][sample_idx, :]
                ))

def MergeRecords(vcftype, num_samples, current_records,
                 mergelist, vcfw, useinfo,
                 useformat, format_type, trim=False):
    r"""Merge records from different files

    Merge all records with indicator set to True in mergelist
    Output merged record to vcfw

    Parameters
    ----------
    vcftype :
       Type of the readers
    num_samples : list of int
       Number of samples per vcf
    current_records : list of vcf.Record
       List of current records for each reader
    mergelist : list of bool
       Indicates whether to include each reader in merge
    vcfw : file
       File to write output to
    useinfo : list of (str, bool)
       List of (info field, required) to use downstream
    useformat: list of str
       List of format field strings to use downstream
    format_type: list of String
        The type of each format field
    """
    use_ind = [i for i in range(len(mergelist)) if mergelist[i]]
    if len(use_ind)==0: return

    chrom = current_records[use_ind[0]].chrom
    pos = str(current_records[use_ind[0]].pos)

    ref_allele = GetRefAllele(current_records, mergelist, trim=trim)
    if ref_allele is None:
        common.WARNING("Conflicting refs found at {}:{}. Skipping.".format(chrom, pos))
        return

    alt_alleles, mappings = GetAltAlleles(current_records, mergelist, vcftype)

    # Set common fields
    vcfw.write(chrom) #CHROM
    vcfw.write('\t')
    vcfw.write(pos) #POS
    vcfw.write('\t')
    # TODO complain if records have different IDs
    vcfw.write(GetID(current_records[use_ind[0]].vcfrecord.ID)) # ID
    vcfw.write('\t')
    vcfw.write(ref_allele) # REF
    vcfw.write('\t')
    # ALT
    if len(alt_alleles) > 0:
        vcfw.write(",".join(alt_alleles))
        vcfw.write('\t')
    else:
        vcfw.write('.\t')
    # fields which are always set to empty
    vcfw.write(".\t") # QUAL
    vcfw.write(".\t") # FITLER

    # INFO
    first = True
    for (field, reqd) in useinfo:
        inf = GetInfoItem(current_records, mergelist, field, fail=reqd)
        if inf is not None:
            if not first:
                vcfw.write(';')
            first = False
            vcfw.write(inf)
    vcfw.write('\t')

    # FORMAT - add GT to front
    vcfw.write(":".join(["GT"]+useformat))

    # Samples
    alleles = [ref_allele]+alt_alleles
    map_iter = iter(mappings)
    for i in range(len(mergelist)):
        if mergelist[i]:
            WriteSampleData(vcfw, current_records[i], alleles, useformat,
                            format_type, next(map_iter))
        else: # NOCALL
            if num_samples[i] > 0:
                vcfw.write('\t')
                vcfw.write('\t'.join([NOCALLSTRING]*num_samples[i]))

    vcfw.write('\n')

def getargs():  # pragma: no cover
    parser = argparse.ArgumentParser(
        __doc__,
        formatter_class=utils.ArgumentDefaultsHelpFormatter
    )
    ### Required arguments ###
    req_group = parser.add_argument_group("Required arguments")
    req_group.add_argument("--vcfs", help="Comma-separated list of VCF files to merge (must be sorted, bgzipped and indexed)", type=str, required=True)
    req_group.add_argument("--out", help="Prefix to name output files", type=str, required=True)
    req_group.add_argument("--vcftype", help="Options=%s"%[str(item) for item in trh.VcfTypes.__members__], type=str, default="auto")
    ### Special merge options ###
    spec_group = parser.add_argument_group("Special merge options")
    spec_group.add_argument("--update-sample-from-file", help="Use file names, rather than sample header names, when merging", action="store_true")
    spec_group.add_argument("--trim", help="Trim flanking bps and variants from TRs before merging (only for TR callers that specify flanking bps)", action="store_true")
    ### Optional arguments ###
    opt_group = parser.add_argument_group("Optional arguments")
    opt_group.add_argument("--verbose", help="Print out extra info", action="store_true")
    opt_group.add_argument("--quiet", help="Don't print out anything", action="store_true")
    ## Version argument ##
    ver_group = parser.add_argument_group("Version")
    ver_group.add_argument("--version", action="version", version = '{version}'.format(version=__version__))
    ### Parse args ###
    args = parser.parse_args()
    return args


class BadOrderException(Exception):
    pass


def _next_assert_order(reader, record, chroms, idx):
    try:
        next_rec = next(reader)
    except StopIteration:
        return None
    if next_rec.chrom not in chroms:
        common.WARNING((
            "Error: found a record in file {} with "
            "chromosome '{}' which was not found in the contig list "
            "({})").format(idx + 1, next_rec.chrom, ", ".join(chroms)))
        common.WARNING("VCF files must contain a ##contig header line for each chromosome.")
        common.WARNING(
            "If this is only a technical issue and all the vcf "
            "files were truly built against against the "
            "same reference, use bcftools "
            "(https://github.com/samtools/bcftools) to fix the contigs"
            ", e.g.: bcftools reheader -f hg19.fa.fai -o myvcf-readher.vcf.gz myvcf.vcf.gz")
        raise BadOrderException()

    if record is None:
        return next_rec
    if ((chroms.index(next_rec.chrom), next_rec.pos) <
            (chroms.index(record.chrom), record.pos)):
        common.WARNING((
            "Error: In file {} the record following the variant at {}:{} "
            "comes before it. Input files must be sorted."
        ).format(idx + 1, record.chrom, record.pos))
        raise BadOrderException()
    return next_rec


def RecordIterator(readers, chroms, verbose=False, trim=False):
    """
    TODO
    Get the next set of records with the same refs

    First skip the records marked by increment which
    have already been processed

    Parameters
    ----------
    readers : list of cyvcf2.VCF
        The VCFs being read
    current_records : list of cyvcf2.Variant
        The records that have already been read
    increment : list of bool
        Which of the current records have been processed

    Returns
    -------
    new_records : list of cyvcf2.Variant
        List of records for each file where the records
        with minimum position have the same refs
    min_pos : list of bool
        Indicates which of the returned records have minimum position
    """
    is_min = [True]*len(readers)
    records = [None]*len(readers)
    curr_chrom_idx = 0 # the chrom of the min records
    prev_pos_end = -np.inf # the pos of the end of any record
                           # marked as min so far
    # iterate until done
    while True:
        # increment all readers that have already been processed because:
        # * they've already been returned to the user
        # * they have bad overlaps and the user has been told they are being
        #   skipped
        # * this is the start and we need to completely refresh the list
        for idx in range(len(readers)):
            if is_min[idx]:
                is_min[idx] = False
                try:
                    records[idx] = _next_assert_order(
                        readers[idx], records[idx], chroms, idx
                    )
                except StopIteration:
                    records.append(None)

        # stop if there are no more records
        if all(r is None for r in records):
            break

        # iterate through the records, collecting the records of minimum
        # position and seeing if they imporperly overlap any other records.
        # repeat only if we don't find any records with the
        # current chromosome, in that case increment the chrom by one and
        # repeat
        min_pos = np.inf # the minimum position seen so far
        min_idxs = None
        overlap = False
        curr_pos_end = -np.inf
        seen_chrom = False
        while not seen_chrom:
            seen_chrom = True
            for idx in range(len(readers)):
                rec = records[idx]
                if rec is None:
                    continue
                chrom_idx = chroms.index(rec.chrom)
                if chrom_idx > curr_chrom_idx:
                    continue
                ## chrom_idx == cur_chrom_idx

                if trim:
                    pos = rec.trimmed_pos
                    end_pos = rec.trimmed_end_pos
                else:
                    pos = rec.pos
                    end_pos = rec.end_pos

                # figure out if there is an overlap
                if pos <= prev_pos_end: # overlaps with prev round
                    overlap = True
                # strictly less than the current best or matches the current best
                elif end_pos <= min_pos or (pos == min_pos and end_pos ==
                                            curr_pos_end):
                    overlap = False
                # overlaps the current best
                elif (pos <= min_pos <= end_pos or
                      min_pos <= pos <= curr_pos_end):
                    overlap = True

                if pos < min_pos:
                    # found a new min record
                    min_idxs = {idx}
                    min_pos = pos
                    curr_pos_end = end_pos
                    continue
                if (pos, end_pos) == (min_pos, curr_pos_end):
                    # found an identical record to merge
                    min_idxs.add(idx)
                    continue
            if min_pos == np.inf:
                seen_chrom = False
                curr_chrom_idx += 1
                prev_pos_end = -np.inf
        prev_pos_end = max(prev_pos_end, curr_pos_end)
        for idx in min_idxs:
            is_min[idx] = True

        if overlap:
            for idx in min_idxs:
                common.WARNING(
                    "Warning: locus {}:{} in file {} overlaps a previous record in "
                    "the same file or a record in another file. Skipping.".format(
                        records[idx].chrom, records[idx].pos, idx+1
                ))
        else:
            if verbose:
                mergeutils.DebugPrintRecordLocations(
                    [record.vcfrecord for record in records],
                    is_min
                )
            yield records, is_min
        # continue while iteration over all records


def main(args):
    if not os.path.exists(os.path.dirname(os.path.abspath(args.out))):
        common.WARNING("Error: The directory which contains the output location {} does"
                       " not exist".format(args.out))
        return 1

    if os.path.isdir(args.out) and args.out.endswith(os.sep):
        common.WARNING("Error: The output location {} is a "
                       "directory".format(args.out))
        return 1

    filenames = args.vcfs.split(",")
    ### Check and Load VCF files ###
    vcfreaders = utils.LoadReaders(filenames, checkgz = True)
    if vcfreaders is None:
        return 1
    if len(vcfreaders) == 0: return 1

    num_samples = [len(reader.samples) for reader in vcfreaders]

    # WriteMergedHeader will confirm that the list of contigs is the same for
    # each vcf, so just pulling it from one here is fine
    chroms = utils.GetContigs(vcfreaders[0])

    ### Check inferred type of each is the same
    try:
        vcftype = mergeutils.GetAndCheckVCFType(vcfreaders, args.vcftype)
    except ValueError as ve:
        common.WARNING('Error: ' + str(ve))
        return 1

    if args.trim and vcftype != trh.VcfTypes.hipstr:
        common.WARNING("Error: trimming flanking bps currently only works "
                       "with HipSTR input.")
        return 1

    ### Set up VCF writer ###
    vcfw = open(args.out + ".vcf", "w")

    useinfo, useformat = WriteMergedHeader(vcfw, args, vcfreaders, " ".join(sys.argv), vcftype)

    if useinfo is None or useformat is None:
        common.WARNING("Error writing merged header. Quitting")
        return 1

    #need to know format types to know how to convert them to strings
    format_type = []
    for fmt in useformat:
        format_type.append(vcfreaders[0].get_header_type(fmt)['Type'])

    # wrap each reader in the TRHarmonizer
    for idx in range(len(vcfreaders)):
        vcfreaders[idx] = trh.TRRecordHarmonizer(vcfreaders[idx], vcftype)

    ### Walk through sorted readers, merging records as we go ###
    try:
        for records, is_min in RecordIterator(
                vcfreaders, chroms, verbose=args.verbose, trim=args.trim):
            MergeRecords(vcftype, num_samples, records, is_min, vcfw, useinfo,
                         useformat, format_type, trim=args.trim)
    except BadOrderException:
        return 1

    return 0

def run(): # pragma: no cover
    args = getargs()
    retcode = main(args)
    sys.exit(retcode)

if __name__ == "__main__": # pragma: no cover
    run()
