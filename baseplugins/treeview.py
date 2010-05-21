#!/usr/bin/env python
# -*- coding: ISO-8859-1 -*-
# treeview.py
"""dicompyler plugin that displays a tree view of the DICOM data structure."""
# Copyright (c) 2010 Aditya Panchal
# This file is part of dicompyler, relased under a BSD license.
#    See the file license.txt included with this distribution, also
#    available at http://code.google.com/p/dicompyler/
#

import threading, Queue
import wx
from wx.xrc import XmlResource, XRCCTRL, XRCID
from wx.lib.pubsub import Publisher as pub
from wx.gizmos import TreeListCtrl as tlc
import guiutil, util
import dicom

def pluginProperties():
    """Properties of the plugin."""

    props = {}
    props['name'] = 'DICOM Tree'
    props['description'] = "Display a tree view of the DICOM data stucture"
    props['author'] = 'Aditya Panchal'
    props['version'] = 0.4
    props['plugin_type'] = 'main'
    props['plugin_version'] = 1
    props['min_dicom'] = ['']
    props['recommended_dicom'] = ['rtss', 'rtdose', 'rtss', 'ct']

    return props

def pluginLoader(parent):
    """Function to load the plugin."""

    # Load the XRC file for our gui resources
    res = XmlResource(util.GetBasePluginsPath('treeview.xrc'))

    panelTreeView = res.LoadPanel(parent, 'pluginTreeView')
    panelTreeView.Init(res)
    
    return panelTreeView
        
class pluginTreeView(wx.Panel):
    """Plugin to display DICOM data in a tree view."""

    def __init__(self):
        pre = wx.PrePanel()
        # the Create step is done by XRC.
        self.PostCreate(pre)

    def Init(self, res):
        """Method called after the panel has been initialized."""

        # Initialize the panel controls
        self.choiceDICOM = XRCCTRL(self, 'choiceDICOM')
        self.tlcTreeView = DICOMTree(self)
        res.AttachUnknownControl('tlcTreeView', self.tlcTreeView, self)

        # Bind interface events to the proper methods
        wx.EVT_CHOICE(self, XRCID('choiceDICOM'), self.OnLoadTree)

        # Decrease the font size on Mac
        font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        if guiutil.IsMac():
            font.SetPointSize(10)
            self.tlcTreeView.SetFont(font)

        # Set up pubsub
        pub.subscribe(self.OnUpdatePatient, 'patient.updated.raw_data')

    def OnUpdatePatient(self, msg):
        """Update and load the patient data."""
        
        self.choiceDICOM.Enable()
        self.choiceDICOM.Clear()
        self.choiceDICOM.Append("Select a DICOM dataset...")
        self.choiceDICOM.Select(0)
        self.tlcTreeView.DeleteAllItems()
        # Iterate through the message and enumerate the DICOM datasets
        for k, v in msg.data.iteritems():
            if isinstance(v, dicom.dataset.FileDataset):
                i = self.choiceDICOM.Append(v.SOPClassUID.name.split(' Storage')[0])
                self.choiceDICOM.SetClientData(i, v)
            # Add the images to the choicebox
            if (k == 'images'):
                for image in v:
                    i = self.choiceDICOM.Append(
                        image.SOPClassUID.name.split(' Storage')[0] + \
                        ' Slice ' + str(image.InstanceNumber))
                    self.choiceDICOM.SetClientData(i, image)

    def OnLoadTree(self, event):
        """Update and load the DICOM tree."""
        
        choiceItem = event.GetInt()
        # Load the dataset chosen from the choice control
        if not (choiceItem == 0):
            dataset = self.choiceDICOM.GetClientData(choiceItem)
        else:
            return
        
        self.tlcTreeView.DeleteAllItems()
        self.root = self.tlcTreeView.AddRoot(text=dataset.SOPClassUID.name)
        self.tlcTreeView.Collapse(self.root)

        # Initialize the progress dialog
        dlgProgress = guiutil.get_progress_dialog(
            wx.GetApp().GetTopWindow(),
            "Loading DICOM data...")
        # Set up the queue so that the thread knows which item was added
        self.queue = Queue.Queue()
        # Initialize and start the recursion thread
        self.t=threading.Thread(target=self.RecurseTreeThread,
            args=(dataset, self.root, self.AddItemTree,
            dlgProgress.OnUpdateProgress, len(dataset)))
        self.t.start()
        # Show the progress dialog
        dlgProgress.ShowModal()
        self.tlcTreeView.SetFocus()
        self.tlcTreeView.Expand(self.root)

    def RecurseTreeThread(self, ds, parent, addItemFunc, progressFunc, length):
        """Recursively process the DICOM tree."""
        for i, data_element in enumerate(ds):
            # Check and update the progress of the recursion
            if (length > 0):
                wx.CallAfter(progressFunc, i, length, 'Processing DICOM data...')
                if (i == length-1):
                    wx.CallAfter(progressFunc, i, len(ds), 'Done')
            # Add the data_element to the tree if not a sequence element
            if not (data_element.VR == 'SQ'):
                wx.CallAfter(addItemFunc, data_element, parent)
            # Otherwise add the sequence element to the tree
            else:
                wx.CallAfter(addItemFunc, data_element, parent, needQueue=True)
                item = self.queue.get()
                # Enumerate for each child element of the sequence
                for i, ds in enumerate(data_element.value):
                    sq_item_description = data_element.name.replace(" Sequence", "")
                    sq_element_text = "%s %d" % (sq_item_description, i+1)
                    # Add the child of the sequence to the tree
                    wx.CallAfter(addItemFunc, data_element, item, sq_element_text, needQueue=True)
                    sq = self.queue.get()
                    self.RecurseTreeThread(ds, sq, addItemFunc, progressFunc, 0)

    def AddItemTree(self, data_element, parent, sq_element_text="", needQueue=False):
        """Add a new item to the DICOM tree."""

        # Set the item if it is a child of a sequence element
        if not (sq_element_text == ""):
            item = self.tlcTreeView.AppendItem(parent, text=sq_element_text)
        else:
            # Account for unicode or string values
            if isinstance(data_element.value, unicode):
                item = self.tlcTreeView.AppendItem(parent, text=unicode(data_element.name))
            else:
                item = self.tlcTreeView.AppendItem(parent, text=str(data_element.name))
            # Set the value if not a sequence element
            if not (data_element.VR == 'SQ'):
                if (data_element.name == 'Pixel Data'):
                    arrayLen = 'Array of ' + str(len(data_element.value)) + ' bytes'
                    self.tlcTreeView.SetItemText(item, arrayLen, 1)
                elif (data_element.name == 'Private tag data'):
                    self.tlcTreeView.SetItemText(item, 'Private tag data', 1)
                else:
                    self.tlcTreeView.SetItemText(item, unicode(data_element.value), 1)
            # Fill in the rest of the data_element properties
            self.tlcTreeView.SetItemText(item, unicode(data_element.tag), 2)
            self.tlcTreeView.SetItemText(item, unicode(data_element.VM), 3)
            self.tlcTreeView.SetItemText(item, unicode(data_element.VR), 4)
        if (needQueue):
            self.queue.put(item)

class DICOMTree(tlc):
    """DICOM tree view based on TreeListControl."""
    
    def __init__(self, *args, **kwargs):
        super(DICOMTree, self).__init__(*args, **kwargs)
        self.AddColumn('Name')
        self.AddColumn('Value')
        self.AddColumn('Tag')
        self.AddColumn('VM')
        self.AddColumn('VR')
        self.SetMainColumn(0)
        self.SetColumnWidth(0, 200)
        self.SetColumnWidth(1, 200)
        self.SetColumnWidth(3, 50)
        self.SetColumnWidth(4, 50)