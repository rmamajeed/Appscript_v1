/* * ======================================================================================
 * MASTER SCRIPT: RFQ INTELLIGENCE (STATEFUL / CONTEXT-AWARE VERSION)
 * Features: Auto-Filing + Deduplication + AI Memory + Timeline Dossier + Junk Filter + RAG Naming + Localized Error Logging + TAT Tracking
 * ======================================================================================
 */

// --- CONFIGURATION ---
var PARENT_FOLDER_ID = '1UYCwSdNaWQ7_TJX4P_cJvgNmExtrkcFr'; 
var SHEET_ID = '1AQQK7xK-fY3xfGXJJSpCk-Wvl39IS2-NXwuVlO10OwM';
var API_KEY = 'AIzaSyDVFJtWHYu1FBz7szxmoyLLbFFDHnOXtVo';
var SEARCH_QUERY = 'subject:RFQ -label:PROCESSED_BY_BOT'; 
var PROCESSED_LABEL_NAME = 'PROCESSED_BY_BOT'; 
var BATCH_SIZE = 2; 

function processRFQs() {
  var startTime = new Date().getTime(); 

  try {
    var parentFolder = DriveApp.getFolderById(PARENT_FOLDER_ID);
    var sheet = SpreadsheetApp.openById(SHEET_ID).getSheetByName("Sheet1"); 
  } catch (e) {
    Logger.log("CRITICAL ERROR: Check Folder/Sheet ID. " + e.toString());
    return;
  }
  
  var processedLabel = getOrCreateLabel(PROCESSED_LABEL_NAME);
  var threads = GmailApp.search(SEARCH_QUERY, 0, BATCH_SIZE);
  
  if (threads.length === 0) { Logger.log("No new RFQs found."); return; }
  Logger.log("Found " + threads.length + " new threads.");

  // --- LOOP THROUGH THREADS ---
  for (var i = 0; i < threads.length; i++) {
    
    if (new Date().getTime() - startTime > 330000) { 
      Logger.log("⚠️ Time Limit Approaching. Stopping batch.");
      break; 
    }

    var thread = threads[i];
    var messages = thread.getMessages(); 
    var subject = thread.getFirstMessageSubject();
    var rfqFolder = null; 
    var skippedFiles = []; 
    
    // --- TRY/CATCH BLOCK FOR ISOLATED ERROR HANDLING ---
    try {
      // 1. SMART FOLDER FINDING 
      var rfqId = extractRfqId(subject); 

      if (rfqId) {
        var searchIterator = parentFolder.searchFolders("title contains '" + rfqId + "'");
        if (searchIterator.hasNext()) { rfqFolder = searchIterator.next(); }
      }

      // If we STILL don't have a folder
      if (!rfqFolder) {
        var tempName = rfqId ? (rfqId + " - " + sanitizeFolderName(subject)) : sanitizeFolderName(subject);
        if (tempName.length > 50) tempName = tempName.substring(0, 50); 
        
        var safeSearchName = tempName.replace(/'/g, "\\'"); 
        var exactSearch = parentFolder.searchFolders("title = '" + safeSearchName + "'");
        
        if (exactSearch.hasNext()) {
          rfqFolder = exactSearch.next(); 
        } else {
          rfqFolder = parentFolder.createFolder(tempName); 
        }
      }

      // 2. FETCH EXISTING CONTEXT
      var existingContext = null;
      if (rfqId) {
        existingContext = getExistingRowData(sheet, rfqId);
      }

      // 3. GATHER EMAIL DATA
      var fullEmailHistory = "SUBJECT: " + subject + "\n\n";
      var aiAttachments = []; 

      for (var j = 0; j < messages.length; j++) {
        var message = messages[j];
        fullEmailHistory += "--- EMAIL " + (j+1) + " ---\n";
        fullEmailHistory += "FROM: " + message.getFrom() + "\n";
        fullEmailHistory += "DATE: " + message.getDate() + "\n";
        fullEmailHistory += "BODY: " + message.getPlainBody() + "\n\n"; 
        
        saveEmailBodyAsPdf(message, rfqFolder, j); 

        var attachments = message.getAttachments({includeInlineImages: true});
        
        for (var k = 0; k < attachments.length; k++) {
          var att = attachments[k];
          
          var mimeType = att.getContentType();
          var sizeInBytes = att.getSize();
          
          if (mimeType.indexOf('image/') === 0 && sizeInBytes < 20480) {
            Logger.log("Skipped tiny inline image: " + att.getName());
            skippedFiles.push("Email " + (j+1) + ": " + (att.getName() || "Unnamed_Image") + " (" + Math.round(sizeInBytes/1024) + " KB)");
            continue; 
          }
          
          var savedFile = saveAttachment(att, rfqFolder, message, j);
          
          if (att.getContentType() === MimeType.PDF) { 
              aiAttachments.push(savedFile); 
          }
        }
      }

      // 4. CALL GEMINI (THE BRAIN)
      var extractionResult = callGeminiStateful(fullEmailHistory, aiAttachments, existingContext);

      // 5. UPDATE TIMELINE DOSSIER & CALCULATE TAT FIRST
      var calculatedAvgTat = ""; // Default to blank
      if (rfqId && extractionResult.interaction_timeline && Array.isArray(extractionResult.interaction_timeline)) {
        // We capture the returned Average TAT from the timeline function
        calculatedAvgTat = updateTimelineSheet(rfqFolder, rfqId, extractionResult.client_name, extractionResult.interaction_timeline);
      }

      // 6. UPDATE MASTER SHEET WITH THE NEW TAT INCLUDED
      updateOrAppendSheetRow(sheet, extractionResult, rfqFolder.getUrl(), rfqId, existingContext, calculatedAvgTat);
      
      // 7. RENAME FOLDER IF APPLICABLE
      if (rfqId && extractionResult.client_name && extractionResult.client_name !== "Unknown") {
        var cleanClient = extractionResult.client_name.toUpperCase().replace(/[\\/:*?"<>|]/g, "");
        var newFolderName = rfqId + " - " + cleanClient;
        
        if (rfqFolder.getName() !== newFolderName) {
          Logger.log("✨ Renaming folder to: " + newFolderName);
          rfqFolder.setName(newFolderName);
        }
      }

      thread.addLabel(processedLabel);
      Logger.log("✅ Successfully processed and labeled thread: " + subject);

      if (skippedFiles.length > 0) {
        saveErrorLogFile(rfqFolder, subject, null, skippedFiles);
      }

    } catch (err) {
      Logger.log("❌ Error processing thread '" + subject + "': " + err.toString());
      if (rfqFolder) {
        saveErrorLogFile(rfqFolder, subject, err.toString(), skippedFiles);
      }
    }

    if (i < threads.length - 1) { Utilities.sleep(30000); }
  }
}

/* * ======================================================================================
 * HELPER FUNCTIONS
 * ======================================================================================
 */

function saveErrorLogFile(folder, subject, errorMessage, skippedFiles) {
  var dateString = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd_HH-mm-ss");
  var fileName = errorMessage ? "ErrorLog_" + dateString + ".txt" : "AuditLog_SkippedFiles_" + dateString + ".txt";

  var content = "=========================================\n" +
                (errorMessage ? "ERROR LOG - RFQ AUTOMATION SYSTEM\n" : "AUDIT LOG - SKIPPED FILES\n") +
                "=========================================\n" +
                "Timestamp: " + new Date().toString() + "\n" +
                "Subject: " + subject + "\n\n";

  if (errorMessage) {
    content += "Error Details:\n" + errorMessage + "\n";
    content += "=========================================\n" +
               "Note: The bot skipped labeling this thread and will attempt to retry it automatically.\n\n";
  }

  if (skippedFiles && skippedFiles.length > 0) {
    content += "Skipped Inline Images (Likely Signatures/Logos):\n";
    for (var i = 0; i < skippedFiles.length; i++) {
      content += "- " + skippedFiles[i] + "\n";
    }
    content += "\n=========================================\n";
  }

  folder.createFile(fileName, content, MimeType.PLAIN_TEXT);
}

function getExistingRowData(sheet, rfqId) {
  var textFinder = sheet.getRange("B:B").createTextFinder(rfqId);
  var foundCell = textFinder.matchEntireCell(false).findNext();
  if (foundCell) {
    var row = foundCell.getRow();
    var data = sheet.getRange(row, 1, 1, 16).getValues()[0];
    return {
      "system_created_date": data[0], 
      "rfq_id": data[1], "client_name": data[2], "insurer": data[3],
      "premium": data[4], "status": data[5], "policy_type": data[6],
      "sentiment": data[7], "urgency": data[8], "missing_docs": data[9],
      "avg_tat": data[15]
    };
  }
  return null;
}

function callGeminiStateful(emailText, pdfFilesArray, existingContext) {
  var url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=" + API_KEY;
  
  var contextPrompt = "";
  if (existingContext) {
    contextPrompt = "CURRENT DATABASE RECORD (What we already know):\n" + JSON.stringify(existingContext) + "\n\n" +
                    "INSTRUCTION: Compare the New Email Data below with the Current Database Record.\n" +
                    "- If the new email adds info (e.g., new price, changed status), UPDATE the record.\n" +
                    "- If the new email is vague/generic, KEEP the old values from the Database Record.\n\n";
  } else {
    contextPrompt = "CURRENT DATABASE RECORD: None (New Entry)\n\n";
  }

  var parts = [
    { "text": "Analyze this Insurance RFQ.\n\n" + 
              contextPrompt + 
              "NEW EMAIL HISTORY:\n" + emailText + "\n\n" +
              "TASK: Return the final, merged JSON for this deal:\n" + 
              "- rfq_id\n" +
              "- client_name (Extract the full official company name)\n" + 
              "- insurer\n" + 
              "- premium (Number only)\n" + 
              "- status\n" +
              "- policy_type\n" +
              "- sentiment\n" +
              "- urgency\n" +
              "- missing_docs\n" +
              "- competitor\n" +
              "- thread_created_date (Format strictly as YYYY-MM-DD HH:MM:SS)\n" +
              "- thread_last_modified_date (Format strictly as YYYY-MM-DD HH:MM:SS)\n" +
              "- interaction_timeline (Array of objects for EACH email in the NEW EMAIL HISTORY. Each object must have 'date' [Format strictly as YYYY-MM-DD HH:MM:SS], 'sender' [MUST extract the exact email address containing the @ symbol from the FROM line. Do not just return the person's name.], and 'summary' [1-line summary of that specific email])\n" +
              "Return ONLY valid JSON." }
  ];

  if (pdfFilesArray && pdfFilesArray.length > 0) {
    for (var i = 0; i < pdfFilesArray.length; i++) {
      var base64Data = Utilities.base64Encode(pdfFilesArray[i].getBlob().getBytes());
      parts.push({ "inline_data": { "mime_type": "application/pdf", "data": base64Data } });
    }
  }

  var payload = { "contents": [{ "parts": parts }] };
  return sendToGemini(url, payload);
}

// --- DOSSIER MANAGER & TAT CALCULATOR ---
function updateTimelineSheet(rfqFolder, rfqId, clientName, timelineData) {
  var safeClient = (clientName && clientName !== "Unknown") ? clientName.toUpperCase().replace(/[\\/:*?"<>|]/g, "") : "Unknown";
  var expectedPrefix = "Timeline_" + rfqId;
  
  // FIX: Look for ANY Google Sheet in the folder that starts with the RFQ ID, ignoring the specific client name suffix
  var files = rfqFolder.getFilesByType(MimeType.GOOGLE_SHEETS);
  var existingFile = null;
  
  while (files.hasNext()) {
    var f = files.next();
    if (f.getName().indexOf(expectedPrefix) === 0) {
      existingFile = f;
      break;
    }
  }

  var timelineSheetId;
  var sheet;

  if (existingFile) {
    timelineSheetId = existingFile.getId();
    sheet = SpreadsheetApp.openById(timelineSheetId).getSheets()[0];
    
    // Optional: We can update the filename to match the newest extracted name if it changed
    var newExpectedName = expectedPrefix + "_" + safeClient;
    if (existingFile.getName() !== newExpectedName) {
      existingFile.setName(newExpectedName);
    }

  } else {
    var ssName = expectedPrefix + "_" + safeClient;
    var newSS = SpreadsheetApp.create(ssName);
    timelineSheetId = newSS.getId();
    var file = DriveApp.getFileById(timelineSheetId);
    file.moveTo(rfqFolder); 
    
    sheet = SpreadsheetApp.openById(timelineSheetId).getSheets()[0];
    sheet.appendRow(["Date", "Sender", "Summary", "Turnaround Time (Hrs)", "Average TAT (Hrs)"]);
    sheet.getRange("A1:E1").setFontWeight("bold").setBackground("#f3f3f3");
    sheet.setColumnWidth(1, 150);
    sheet.setColumnWidth(2, 250);
    sheet.setColumnWidth(3, 600);
    sheet.setColumnWidth(4, 150);
    sheet.setColumnWidth(5, 150);
  }

  var data = sheet.getDataRange().getValues();
  var existingKeys = new Set();
  
  for(var i = 1; i < data.length; i++) {
    var existingDate = data[i][0] instanceof Date ? Utilities.formatDate(data[i][0], Session.getScriptTimeZone(), "yyyy-MM-dd HH:mm:ss") : data[i][0];
    existingKeys.add(existingDate + "_" + data[i][1] + "_" + String(data[i][2]).substring(0, 30)); 
  }

  for(var i = 0; i < timelineData.length; i++) {
    var row = timelineData[i];
    var key = row.date + "_" + row.sender + "_" + String(row.summary).substring(0, 30);
    
    if(!existingKeys.has(key)) {
      sheet.appendRow([row.date, row.sender, row.summary, "", ""]);
      existingKeys.add(key); 
    }
  }

  var fullData = sheet.getDataRange().getValues();
  if (fullData.length <= 1) return ""; 

  var headers = fullData[0];
  headers[3] = "Turnaround Time (Hrs)";
  headers[4] = "Average TAT (Hrs)";

  var rows = fullData.slice(1);

  rows.forEach(function(r) {
    var d = new Date(r[0]);
    if (isNaN(d.getTime()) && typeof r[0] === 'string') {
      d = new Date(r[0].replace(/-/g, '/')); 
    }
    r.push(d); 
  });

  rows.sort(function(a, b) {
    return a[a.length - 1] - b[b.length - 1];
  });

  var firstCustomerEmailTime = null;
  var totalTatHours = 0;
  var tatCount = 0;

  for (var i = 0; i < rows.length; i++) {
    var r = rows[i];
    var sender = String(r[1]).toLowerCase();
    var isInternal = sender.indexOf("@orbee.com.qa") !== -1 || sender.indexOf("orbee") !== -1;
    var rowDate = r[r.length - 1]; 

    r[3] = ""; 
    r[4] = ""; 

    if (!isInternal) {
      if (firstCustomerEmailTime === null) {
        firstCustomerEmailTime = rowDate;
      }
    } else {
      if (firstCustomerEmailTime !== null) {
        var diffMs = rowDate - firstCustomerEmailTime;
        var diffHours = diffMs / (1000 * 60 * 60);
        r[3] = diffHours.toFixed(2); 
        totalTatHours += diffHours;
        tatCount++;
        firstCustomerEmailTime = null; 
      }
    }
  }

  var avgTat = tatCount > 0 ? (totalTatHours / tatCount).toFixed(2) : "";
  if (rows.length > 0) {
    rows[0][4] = avgTat; 
  }

  var outputData = [headers.slice(0, 5)];
  for (var i = 0; i < rows.length; i++) {
    outputData.push(rows[i].slice(0, 5));
  }

  sheet.getRange(1, 1, outputData.length, 5).setValues(outputData);

  return avgTat;
}

function updateOrAppendSheetRow(sheet, data, link, originalId, existingContext, calculatedAvgTat) {
  var currentTimestamp = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd HH:mm:ss");
  var finalId = data.rfq_id || originalId || "N/A";
  
  var createdDate = (existingContext && existingContext.system_created_date) ? existingContext.system_created_date : currentTimestamp;
  var lastModifiedDate = currentTimestamp;
  
  var rowData = [
    createdDate, finalId, data.client_name || "Unknown", data.insurer || "Unknown",
    data.premium || 0, data.status || "Pending", data.policy_type || "General", 
    data.sentiment || "Neutral", data.urgency || "Low", data.missing_docs || "None", 
    data.competitor || "None", link, lastModifiedDate, 
    data.thread_created_date || "Unknown", data.thread_last_modified_date || "Unknown",
    calculatedAvgTat || (existingContext ? existingContext.avg_tat : "") 
  ];

  var textFinder = sheet.getRange("B:B").createTextFinder(finalId);
  var foundCell = textFinder.matchEntireCell(false).findNext();

  if (foundCell && finalId !== "N/A") {
    var rowRow = foundCell.getRow();
    sheet.getRange(rowRow, 1, 1, 16).setValues([rowData]);
  } else {
    sheet.appendRow(rowData);
  }
}

function sendToGemini(url, payload) {
  var options = { "method": "post", "contentType": "application/json", "payload": JSON.stringify(payload), "muteHttpExceptions": true };
  
  var response = UrlFetchApp.fetch(url, options);
  var responseCode = response.getResponseCode();
  var responseText = response.getContentText();

  if (responseCode !== 200) {
    throw new Error("HTTP " + responseCode + " Error. Details: " + responseText);
  }

  var json = JSON.parse(responseText);
  
  if (!json.candidates || json.candidates.length === 0) {
    throw new Error("API succeeded but returned no candidates. Possible safety block. Raw response: " + responseText);
  }

  var aiText = json.candidates[0].content.parts[0].text;
  
  try {
    return JSON.parse(aiText.replace(/```json/g, "").replace(/```/g, "").trim());
  } catch (e) {
    throw new Error("Failed to parse AI output as JSON. AI Output was: " + aiText);
  }
}

function saveEmailBodyAsPdf(message, folder, index) {
  var subject = message.getSubject();
  var dateString = Utilities.formatDate(message.getDate(), Session.getScriptTimeZone(), "yyyy-MM-dd");
  var safeSubject = sanitizeFolderName(subject);
  if (safeSubject.length > 50) safeSubject = safeSubject.substring(0, 50);
  
  var fileName = "Email_" + dateString + "_" + safeSubject + "_" + index + ".pdf";
  var existing = folder.getFilesByName(fileName);
  
  if (existing.hasNext()) { return existing.next(); }
  
  var html = "<h3>" + subject + "</h3>" + message.getBody();
  var blob = Utilities.newBlob(html, "text/html", fileName);
  var pdf = blob.getAs("application/pdf");
  pdf.setName(fileName);
  return folder.createFile(pdf);
}

function extractRfqId(text) {
  var flexRegex = /(RFQ[-a-zA-Z\s]+\d+)/i; 
  var match = text.match(flexRegex);
  
  if (match) {
    return match[0].toUpperCase().replace(/\s+/g, "").replace(/-+/g, "-");
  }
  return null; 
}

function saveAttachment(att, folder, message, index) {
  var subject = message.getSubject();
  var dateString = Utilities.formatDate(message.getDate(), Session.getScriptTimeZone(), "yyyy-MM-dd");
  var safeSubject = sanitizeFolderName(subject);
  if (safeSubject.length > 50) safeSubject = safeSubject.substring(0, 50);

  var originalName = att.getName();
  if (originalName.length > 100) originalName = originalName.substring(0, 100);

  var newName = "Att_" + dateString + "_" + safeSubject + "_" + index + "_" + originalName;
  var existing = folder.getFilesByName(newName);
  
  if (existing.hasNext()) { return existing.next(); }
  
  att.setName(newName);
  return folder.createFile(att);
}

function sanitizeFolderName(name) { return name.replace(/[\\/:*?"<>|]/g, "_").substring(0, 50); }
function getOrCreateLabel(name) { var label = GmailApp.getUserLabelByName(name); if (!label) { label = GmailApp.createLabel(name); } return label; }