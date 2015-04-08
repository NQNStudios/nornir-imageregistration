'''
Created on Dec 13, 2013

@author: James Anderson
'''

import unittest
from . import setup_imagetest
import glob
import nornir_imageregistration.assemble_tiles as at
import nornir_imageregistration.tileset as tileset 
import nornir_imageregistration.core as core
import nornir_imageregistration.layout
from nornir_imageregistration.alignment_record import AlignmentRecord
from nornir_imageregistration.files.mosaicfile import MosaicFile
import os
import nornir_imageregistration.transforms.factory as tfactory
# from pylab import *
from scipy.misc import imsave
import numpy as np
from scipy import stats
import nornir_imageregistration.arrange_mosaic as arrange

import nornir_pools
from nornir_shared.tasktimer import TaskTimer
import nornir_shared.plot

import nornir_imageregistration.mosaic
from nornir_imageregistration.mosaic import Mosaic


def _GetFirstOffsetPair(layout_obj):
    '''Return the first offset from the tile list'''

    NodeA = layout_obj.nodes[0]
    NodeB_ID = NodeA.ConnectedIDs[0]
    NodeB = layout_obj.nodes[NodeB_ID]
    NodeB_Offset = NodeA.GetOffset(NodeB_ID)
    
    return (NodeA, NodeB, NodeB_Offset)


class TestBasicTileAlignment(setup_imagetest.MosaicTestBase):

    def test_Alignments(self):

        Downsample = 1.0
        DownsampleString = "%03d" % Downsample 
        self.TilesPath = os.path.join(self.ImportedDataPath, "PMG1", "Leveled", "TilePyramid", DownsampleString)

        Tile1Filename = "Tile000001.png"
        Tile2Filename = "Tile000002.png"
        Tile5Filename = "Tile000005.png"
        Tile6Filename = "Tile000006.png"
        Tile7Filename = "Tile000007.png"
        Tile9Filename = "Tile000009.png"


        self.RunAlignment(Tile7Filename, Tile9Filename, (908 / Downsample, 0))
        self.RunAlignment(Tile5Filename, Tile6Filename, (2 / Downsample, 1260 / Downsample))
        self.RunAlignment(Tile1Filename, Tile2Filename, (4 / Downsample, 1260 / Downsample))


    def test_MismatchSizeAlignments(self):

        self.TilesPath = os.path.join(self.TestInputPath, "Images", "Alignment")

        Tile1Filename = "402.png"
        Tile2Filename = "401_Subset.png"

        # self.RunAlignment(Tile1Filename, Tile2Filename, (-529, -93))


    def RunAlignment(self, TileAFilename, TileBFilename, ExpectedOffset):
        '''ExpectedOffset is (Y,X)'''

        imFixed = core.LoadImage(os.path.join(self.TilesPath, TileAFilename))
        imMoving = core.LoadImage(os.path.join(self.TilesPath, TileBFilename))

        imFixedPadded = core.PadImageForPhaseCorrelation(imFixed)
        imMovingPadded = core.PadImageForPhaseCorrelation(imMoving)

        alignrecord = core.FindOffset(imFixedPadded, imMovingPadded)
        
        print(str(alignrecord))

        # self.assertAlmostEqual(alignrecord.peak[1], ExpectedOffset[1], delta=2, msg="X dimension incorrect: " + str(alignrecord.peak) + " != " + str(ExpectedOffset))
        # self.assertAlmostEqual(alignrecord.peak[0], ExpectedOffset[0], delta=2, msg="Y dimension incorrect: " + str(alignrecord.peak) + " != " + str(ExpectedOffset))


class TestMosaicArrange(setup_imagetest.MosaicTestBase, setup_imagetest.PickleHelper):

    @property
    def Dataset(self):
        return "PMG1"
    
    @property
    def MosaicFiles(self, testName=None):
        if testName is None:
            testName = self.Dataset

        return glob.glob(os.path.join(self.ImportedDataPath, testName, "Stage.mosaic"))


    def RigidTransformForTile(self, tile, arecord=None):
        if arecord is None:
            arecord = AlignmentRecord((0, 0), 0, 0)

        return tfactory.CreateRigidTransform(tile.OriginalImageSize, tile.OriginalImageSize, 0, arecord.peak)

    def ShowTilesWithOffset(self, tileA, tileB, offset):

        # transformA = self.RigidTransformForTile(tileA, AlignmentRecord((0, -624 * 2.0), 0, 0))
        transformA = self.RigidTransformForTile(tileA)
        transformB = self.RigidTransformForTile(tileB, offset)

        ImageToTransform = {}
        ImageToTransform[tileA.ImagePath] = transformA
        ImageToTransform[tileB.ImagePath] = transformB

        mosaic = Mosaic(ImageToTransform)
        mosaic.TranslateToZeroOrigin()

        self._ShowMosaic(mosaic, usecluster=False)

    def _ShowMosaic(self, mosaic, mosaic_path=None, openwindow=True, usecluster=True, title=None):

        (assembledImage, mask) = mosaic.AssembleTiles(tilesPath=None, usecluster=usecluster)
        
        if not mosaic_path is None:
            pool = nornir_pools.GetGlobalThreadPool()
            pool.add_task("Save %s" % mosaic_path, core.SaveImage, mosaic_path, assembledImage)
            #core.SaveImage(mosaic_path, assembledImage)
        
        if openwindow:
            if title is None:
                title="A mosaic with no tiles out of place"
            core.ShowGrayscale(assembledImage, title=title)


    def __CheckNoOffsetsToSelf(self, layout):

        for i, node in layout.nodes.items():
            self.assertFalse(i in node.ConnectedIDs, "Tiles should not be registered to themselves")


    def __RemoveExtraImages(self, mosaic):

        '''Remove all but the first two images'''
        keys = list(mosaic.ImageToTransform.keys())
        keys.sort()

        for i, k in enumerate(keys):
            if i >= 2:
                del mosaic.ImageToTransform[k]

    
    def LoadTilesAndCalculateOffsets(self, transforms, imagepaths, imageScale=None):
        tiles = nornir_imageregistration.tile.CreateTiles(transforms, imagepaths)

        if imageScale is None:
            imageScale = tileset.MostCommonScalar(transforms, imagepaths)
    
        translate_layout = arrange._FindTileOffsets(tiles, imageScale)
        
        self.__CheckNoOffsetsToSelf(translate_layout)
        
        return (translate_layout, tiles)

    def ArrangeMosaicDirect(self, mosaicFilePath, TilePyramidDir=None, parallel=False, downsample=None, openwindow=False):

        if downsample is None:
            downsample = 1
            
        downsamplePath = '%03d' % downsample

        scale = 1.0 / float(downsample)

        mosaic = Mosaic.LoadFromMosaicFile(mosaicFilePath)
        mosaicBaseName = os.path.basename(mosaicFilePath)

        (mosaicBaseName, ext) = os.path.splitext(mosaicBaseName)
        
        TilesDir = None
        if TilePyramidDir is None:
            TilesDir = os.path.join(self.ImportedDataPath, self.Dataset, 'Leveled', 'TilePyramid', downsamplePath)
        else:
            TilesDir = os.path.join(TilePyramidDir, downsamplePath)
              

#        mosaic.TranslateToZeroOrigin()

        # self.__RemoveExtraImages(mosaic)

        # assembleScale = tiles.MostCommonScalar(mosaic.ImageToTransform.values(), mosaic.TileFullPaths(TilesDir))

        # expectedScale = 1.0 / float(downsamplePath)

        #  self.assertEqual(assembleScale, expectedScale, "Scale for assemble does not match the expected scale")

        timer = TaskTimer()

        timer.Start("ArrangeTiles " + TilesDir)

        tilesPathList = sorted(mosaic.CreateTilesPathList(TilesDir))
        
        transforms = list(mosaic._TransformsSortedByKey())
        
        imageScale = self.ReadOrCreateVariable(self.id() + "_imageScale_%03d" % downsample, tileset.MostCommonScalar, transforms=transforms, imagepaths=tilesPathList)
        
        self.assertEqual(imageScale, 1.0 / downsample, "Calculated image scale should match downsample value passed to test")
   
        (translated_layout, tiles) = self.ReadOrCreateVariable(self.id() + "tiles_%03d" % downsample, self.LoadTilesAndCalculateOffsets, transforms=transforms, imagepaths=tilesPathList)
  
        # Each tile should contain a dictionary with the known offsets.  Show the overlapping images using the calculated offsets

        (tileA, tileB, offset) = _GetFirstOffsetPair(translated_layout)
                
        # self.ShowTilesWithOffset(tileA, tileB, offset)
        # mosaic.ArrangeTilesWithTranslate(TilesDir, usecluster=parallel)
        #nornir_imageregistration.layout.ScaleOffsetWeightsByPosition(translated_layout)
        nornir_imageregistration.layout.ScaleOffsetWeightsByPopulationRank(translated_layout, min_allowed_weight=0.25, max_allowed_weight=1.0)
        translated_final_layout = nornir_imageregistration.layout.BuildLayoutWithHighestWeightsFirst(translated_layout)
        translated_mosaic = self.CreateSaveShowMosaic(mosaicBaseName, translated_final_layout, tiles, openwindow)
        
        relaxed_layout = self._Relax_Layout(translated_layout)
        relaxed_mosaic = self.CreateSaveShowMosaic(mosaicBaseName + "_relaxed", relaxed_layout, tiles, openwindow)
        
        #TODO, maybe just run translate again after relax instead of refine?
         
        #translated_transforms = list(relaxed_mosaic._TransformsSortedByKey())
        #(translate_refine_layout, tiles) = nornir_imageregistration.arrange_mosaic.RefineTranslations(translated_transforms, tilesPathList, imageScale)
        #nornir_imageregistration.layout.ScaleOffsetWeightsByPopulationRank(translate_refine_layout, min_allowed_weight=0.25, max_allowed_weight=1.0)
        
        #final_translated_refined_layout = nornir_imageregistration.layout.BuildLayoutWithHighestWeightsFirst(translate_refine_layout)
        #translated_refined_mosaic = self.CreateSaveShowMosaic(mosaicBaseName + "_translated_refined", final_translated_refined_layout, tiles, openwindow)
        
        #translated_refined_relaxed_layout = self._Relax_Layout(translate_refine_layout)
        #translated_refined_relaxed_mosaic = self.CreateSaveShowMosaic(mosaicBaseName + "_translated_refined_relaxed", translated_refined_relaxed_layout, tiles, openwindow)
                 
        original_score = mosaic.QualityScore(TilesDir)    
        translated_score = translated_mosaic.QualityScore(TilesDir)        
        relaxed_score = relaxed_mosaic.QualityScore(TilesDir)
        #translated_refined_score = translated_refined_mosaic.QualityScore(TilesDir)
        #translated_refined_relaxed_score = translated_refined_relaxed_mosaic.QualityScore(TilesDir) 
        
        print("Original Quality Score: %g" % (original_score))
        print("Translated Quality Score: %g" % (translated_score))
        print("Relaxed Quality Score: %g" % (relaxed_score))
        #print("Translated refined Quality Score: %g" % (translated_refined_score))
        #print("Translated refined relaxed Quality Score: %g" % (translated_refined_relaxed_score))
        
        #self.assertLess(translated_score, original_score, "Translated worse than original")
        #self.assertLess(relaxed_score, translated_score, "Translated worse than original")
        
    def CreateSaveShowMosaic(self, name, layout_obj, tiles, openwindow=False):
        OutputDir = os.path.join(self.TestOutputPath, name + '.mosaic')
        OutputMosaicDir = os.path.join(self.TestOutputPath, name + '.png')
        
        created_mosaic = nornir_imageregistration.mosaic.LayoutToMosaic(layout_obj, tiles)
        created_mosaic.SaveToMosaicFile(OutputDir)
        self._ShowMosaic(created_mosaic, OutputMosaicDir, openwindow=False)
        
        return created_mosaic
          
    
    def _Relax_Layout(self, layout_obj, max_tension_cutoff=1, max_iter=50):
                
        max_tension = layout_obj.MaxWeightedTension
         
        i = 0
        
        pool = nornir_pools.GetGlobalMultithreadingPool()
        
        MovieImageDir = os.path.join(self.TestOutputPath, "relax_movie")
        if not os.path.exists(MovieImageDir):
            os.makedirs(MovieImageDir)
            
        while max_tension > max_tension_cutoff and i < max_iter:
            print("%d %g" % (i, max_tension))
            node_movement = nornir_imageregistration.layout.Layout.RelaxNodes(layout_obj)
            max_tension = layout_obj.MaxWeightedTension
            #node_distance = setup_imagetest.array_distance(node_movement[:,1:3])             
            #max_distance = np.max(node_distance,0)
            i += 1
            
            filename = os.path.join(MovieImageDir, "%d.tif" % i)
            
            pool.add_task("Plot step #%d" % (i), nornir_shared.plot.VectorField,layout_obj.GetPositions(), layout_obj.WeightedNetTensionVectors(), filename)
            #nornir_shared.plot.VectorField(layout_obj.GetPositions(), layout_obj.NetTensionVectors(), filename)
            
        return layout_obj

    def ArrangeMosaic(self, mosaicFilePath, TilePyramidDir=None, parallel=False, downsample=None):
 
        if downsample is None:
            downsample = 1
            
        downsamplePath = '%03d' % downsample

        mosaic = Mosaic.LoadFromMosaicFile(mosaicFilePath)
        mosaicBaseName = os.path.basename(mosaicFilePath)

        (mosaicBaseName, ext) = os.path.splitext(mosaicBaseName)

        TilesDir = None
        if TilePyramidDir is None:
            TilesDir = os.path.join(self.ImportedDataPath, self.Dataset, 'Leveled', 'TilePyramid', downsamplePath)
        else:
            TilesDir = os.path.join(TilePyramidDir, downsamplePath)

        mosaic.TranslateToZeroOrigin()
        
        original_score = mosaic.QualityScore(TilesDir)

        # self.__RemoveExtraImages(mosaic)

        assembleScale = tileset.MostCommonScalar(mosaic.ImageToTransform.values(), mosaic.TileFullPaths(TilesDir))

        expectedScale = 1.0 / float(downsamplePath)

        self.assertEqual(assembleScale, expectedScale, "Scale for assemble does not match the expected scale")

        timer = TaskTimer()

        timer.Start("ArrangeTiles " + TilesDir)

        translated_mosaic = mosaic.ArrangeTilesWithTranslate(TilesDir, usecluster=False)

        timer.End("ArrangeTiles " + TilesDir, True)
        
        translated_score = translated_mosaic.QualityScore(TilesDir)
        
        print("Original Quality Score: %g" % (original_score))
        print("Translate Quality Score: %g" % (translated_score))
        
        #self.assertLess(translated_score, original_score, "Quality score should improve after we run translate")
                
        OutputDir = os.path.join(self.TestOutputPath, mosaicBaseName + '.mosaic')
        OutputMosaicDir = os.path.join(self.TestOutputPath, mosaicBaseName + '.png')

        translated_mosaic.SaveToMosaicFile(OutputDir)
        self._ShowMosaic(translated_mosaic, OutputMosaicDir)
         
        
    def test_RC2_0197_Mosaic(self):
        
        self.ArrangeMosaicDirect(mosaicFilePath="D:\\RC2\\TEM\\0197\\TEM\\stage.mosaic", TilePyramidDir="D:\\RC2\\TEM\\0197\\TEM\\Leveled\\TilePyramid", parallel=False, downsample=4, openwindow=False)

        print("All done")
        
    def test_RC2_0001_Mosaic(self):
        
        self.ArrangeMosaicDirect(mosaicFilePath="D:\\RC2\\TEM\\0001\\TEM\\stage.mosaic", TilePyramidDir="D:\\RC2\\TEM\\0001\\TEM\\Leveled\\TilePyramid", parallel=False, downsample=4, openwindow=False)

        print("All done")

    def test_ArrangeMosaic(self):
        
        for m in self.MosaicFiles:
            self.ArrangeMosaic(m, TilePyramidDir=None, parallel=False, downsample=1)

        print("All done")

    def test_ArrangeMosaicDirect(self):

        for m in self.MosaicFiles:
            self.ArrangeMosaicDirect(m, TilePyramidDir=None, parallel=False, downsample=1, openwindow=True)

        print("All done")


if __name__ == "__main__":
    # import sys;sys.argv = ['', 'Test.testName']

    import nornir_shared.misc
    nornir_shared.misc.RunWithProfiler("unittest.main()")
