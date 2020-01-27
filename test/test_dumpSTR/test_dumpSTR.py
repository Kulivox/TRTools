import argparse
import os,sys
import pytest
import vcf
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..','..','dumpSTR'))
from dumpSTR import *


COMMDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common")
DUMPDIR = os.path.join(COMMDIR, "dump")
VCFDIR = os.path.join(COMMDIR, "sample_vcfs")
# Set up base argparser
def base_argparse():
    args = argparse.ArgumentParser()
    args.vcf = None
    args.out = os.path.join(DUMPDIR, "test")
    args.min_locus_callrate = None
    args.min_locus_hwep = None
    args.min_locus_het = None
    args.max_locus_het = None
    args.use_length = False
    args.filter_regions = None
    args.filter_regions_names = None
    args.filter_hrun = False
    args.drop_filtered = False
    args.min_call_DP = None
    args.max_call_DP = None
    args.min_call_Q = None
    args.max_call_flank_indel = None
    args.max_call_stutter = None
    args.min_supp_reads = 0
    args.expansion_prob_het = None
    args.expansion_prob_hom = None
    args.expansion_prob_total = None
    args.filter_span_only = False
    args.filter_spanbound_only = False 
    args.filter_badCI = None
    args.require_support = 0
    args.readlen = None
    args.num_records = None
    args.die_on_warning = False
    args.verbose = False
    return args

# Test no such file or directory
def test_WrongFile():
    args = base_argparse()
    fname = os.path.join(VCFDIR, "test_non_existent.vcf")
    if os.path.exists(fname):
        os.remove(fname)
    args.vcf = fname
    retcode = main(args)
    assert retcode==1


#Test if test works for the right filename 
def test_RightFile():
    args = base_argparse()
    fname = os.path.join(VCFDIR, "test_gangstr.vcf")
    args.vcf = fname
    retcode = main(args)
    assert retcode==0

def test_Filters(): 
    args = base_argparse() 
    fname = os.path.join(VCFDIR, "artificial_gangstr.vcf")
    args.vcf = fname
    artificial_vcf = vcf.Reader(filename=args.vcf)
    
    ## Test1: call passes with no filter
    vcfcall = vcf.model._Call # Blank call
    call_filters = []
    reasons1 = FilterCall(vcfcall, call_filters)
    assert reasons1==[]

    # Line 1 of artificial vcf
    record1 = next(artificial_vcf)
    call1 = record1.samples[0]
    
    ## Check call1 attributes:
    assert record1.CHROM=='chr1'
    assert record1.POS==3004986
    assert record1.REF=='tctgtctgtctg'
    assert record1.INFO['RU']=='tctg'
    assert call1['DP']==31
    assert call1['Q']==0.999912
    assert call1['QEXP']==[0.0, 5.1188e-05, 0.999949]
    assert call1['RC']=='17,12,0,2'

    ## Test2: call filter: LowCallDepth  
    vcfcall = call1
    args = base_argparse()
    args.min_call_DP = 50
    call_filters = BuildCallFilters(args)
    reasons2 = FilterCall(vcfcall, call_filters)
    assert reasons2==['LowCallDepth']
    
    ## Test3: call filter: HighCallDepth
    vcfcall = call1
    args = base_argparse()
    args.max_call_DP = 10
    call_filters = BuildCallFilters(args)
    reasons3 = FilterCall(vcfcall, call_filters)
    assert reasons3==['HighCallDepth']

    ## Test4: call filter: LowCallQ
    vcfcall = call1
    args = base_argparse()
    args.min_call_Q = 1
    call_filters = BuildCallFilters(args)
    reasons4 = FilterCall(vcfcall, call_filters)
    assert reasons4==['LowCallQ']

    ## Test4: call filter: LowCallQ
    vcfcall = call1
    args = base_argparse()
    args.min_call_Q = 1
    call_filters = BuildCallFilters(args)
    reasons4 = FilterCall(vcfcall, call_filters)
    assert reasons4==['LowCallQ']

    ## Test5: call filter: ProbHom
    vcfcall = call1
    args = base_argparse()
    args.expansion_prob_hom = 1
    call_filters = BuildCallFilters(args)
    reasons5 = FilterCall(vcfcall, call_filters)
    assert reasons5==['ProbHom']

    ## Test6: call filter: ProbHet
    vcfcall = call1
    args = base_argparse()
    args.expansion_prob_het = 0.8
    call_filters = BuildCallFilters(args)
    reasons6 = FilterCall(vcfcall, call_filters)
    assert reasons6==['ProbHet']

    # Line 2 of artificial vcf
    record2 = next(artificial_vcf)
    call2 = record2.samples[0]

    ## Check call2 attributes:
    assert record2.CHROM=='chr1'
    assert record2.POS==3005549
    assert record2.REF=='aaaacaaaacaaaacaaaac'
    assert record2.INFO['RU']=='aaaac'
    assert call2['DP']==11
    assert call2['Q']==1
    assert call2['QEXP']==[0.8, 0.2, 0]
    assert call2['RC']=='0,11,0,0'

    ## Test7: call filter: ProbTotal
    vcfcall = call2
    args = base_argparse()
    args.expansion_prob_total = 1
    call_filters = BuildCallFilters(args)
    reasons7 = FilterCall(vcfcall, call_filters)
    assert reasons7==['ProbTotal']

    ## Test8: call filter: filter span only
    vcfcall = call1
    args = base_argparse()
    args.filter_span_only = True
    call_filters = BuildCallFilters(args)
    reasons71 = FilterCall(vcfcall, call_filters)
    assert reasons71==[]

    vcfcall = call2
    args = base_argparse()
    args.filter_span_only = True
    call_filters = BuildCallFilters(args)
    reasons72 = FilterCall(vcfcall, call_filters)
    assert reasons72==['SpanOnly']

    # Line 3 of artificial vcf
    record3 = next(artificial_vcf)
    call3 = record3.samples[0]

    ## Check call2 attributes:
    assert record3.CHROM=='chr1'
    assert record3.POS==3009351
    assert record3.REF=='tgtgtgtgtgtgtgtgtgtgtgtgtgtgtgtgtgtgtgtgtgtgtgtgtgtg'
    assert record3.INFO['RU']=='tg'
    assert call3['DP']==20
    assert call3['RC']=='0,10,0,10'      
 
    ## Test8: call filter: filter span-bound only
    vcfcall = call1
    args = base_argparse()
    args.filter_spanbound_only = True
    call_filters = BuildCallFilters(args)
    reasons81 = FilterCall(vcfcall, call_filters)
    assert reasons81==[]

    vcfcall = call2
    args = base_argparse()
    args.filter_spanbound_only = True
    call_filters = BuildCallFilters(args)
    reasons82 = FilterCall(vcfcall, call_filters)
    assert reasons82==['SpanBoundOnly']

    vcfcall = call3    
    args = base_argparse()
    args.filter_spanbound_only = True
    call_filters = BuildCallFilters(args)
    reasons83 = FilterCall(vcfcall, call_filters)
    assert reasons83==['SpanBoundOnly']